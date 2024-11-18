import argparse
import json
import logging
import logging.handlers
import os
import stat
import subprocess
import sys
import time
from asyncio import Future
from pathlib import Path
from types import TracebackType
from typing import Any, Optional

import regex
from config import MISSIONS, PROGRAM_COMMAND, SETUP_COMMANDS  # type: ignore
from terminado.management import UniqueTermManager
from terminado.websocket import TermSocket
from tornado.ioloop import IOLoop
from tornado.web import Application, StaticFileHandler
from tornado.websocket import WebSocketHandler


class GradeManager:
    GRADE_DIR: Path
    GRADE_FILE: Path
    LOG_FILE: Path
    SERVER_LOG_FILE: Path

    @classmethod
    def set_workdir(cls, workdir: str) -> None:
        """Set working directory for grade files"""
        cls.GRADE_DIR = Path(workdir) / ".checkpoint"
        cls.GRADE_FILE = cls.GRADE_DIR / "results.json"
        cls.LOG_FILE = cls.GRADE_DIR / "session.log"
        cls.SERVER_LOG_FILE = cls.GRADE_DIR / "server.log"

    @classmethod
    def _create_grade_data(
        cls, completed_missions: int, total_missions: int
    ) -> dict[str, Any]:
        """Create grade data structure"""
        score = completed_missions / total_missions if total_missions > 0 else 0
        return {
            "score": score,
            "max_points": 1.0,
            "feedback": {
                "completed_missions": completed_missions,
                "total_missions": total_missions,
                "message": (
                    f"Completed {completed_missions} out of {total_missions} "
                    "missions"
                ),
            },
        }

    @classmethod
    def init(cls) -> None:
        """Initialize grade file, directory and logging"""
        # Create directory and set permissions
        cls.GRADE_DIR.mkdir(exist_ok=True)
        cls.GRADE_DIR.chmod(stat.S_IRWXU)  # 700

        # Setup server logging
        cls.server_logger = logging.getLogger("server")
        cls.server_logger.setLevel(logging.INFO)
        handler = logging.FileHandler(cls.SERVER_LOG_FILE)
        handler.setFormatter(logging.Formatter(fmt="%(asctime)s - %(message)s"))
        cls.server_logger.addHandler(handler)

        def handle_exception(
            exc_type: type[Exception],
            exc_value: Exception,
            exc_traceback: TracebackType,
        ) -> None:
            """Handle uncaught exceptions by logging them to server.log"""
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            cls.server_logger.error(
                "Uncaught exception:", exc_info=(exc_type, exc_value, exc_traceback)
            )

        sys.excepthook = handle_exception

        try:
            # Setup session logging
            logging.basicConfig(
                filename=cls.LOG_FILE,
                level=logging.INFO,
                format="%(asctime)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

            # Initialize grade file
            with open(cls.GRADE_FILE, "w") as f:
                json.dump(cls._create_grade_data(0, len(MISSIONS)), f)

            # Set permissions for files
            cls.GRADE_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
            cls.LOG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
            cls.SERVER_LOG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600

            logging.info("=== New Session Started ===")
            cls.server_logger.info("=== Server Session Started ===")
        except Exception as e:
            cls.server_logger.error(f"Error initializing grade file and logging: {e}")

    @classmethod
    def update(cls, completed_missions: int) -> None:
        """Update grade file"""
        try:
            with open(cls.GRADE_FILE, "w") as f:
                json.dump(cls._create_grade_data(completed_missions, len(MISSIONS)), f)
        except Exception as e:
            cls.server_logger.error(f"Error updating grade file: {e}")


MISSIONS: list[dict[str, Any]]
PROGRAM_COMMAND: list[str]
SETUP_COMMANDS: list[str]


class MissionHandler(WebSocketHandler):
    active_connections: set["MissionHandler"] = set()

    def initialize(self):
        self.current_mission = 0

    def check_origin(self, origin: str) -> bool:
        return True

    def open(self, *args: Any, **kwargs: Any) -> None:
        MissionHandler.active_connections.add(self)
        self.write_message(
            {
                "type": "init",
                "currentMission": self.current_mission,
                "missions": [
                    {
                        "title": m["title"],
                        "prompt": m["prompt"],
                        "description": m["description"],
                    }
                    for m in MISSIONS
                ],
            }
        )
        GradeManager.update(self.current_mission)

    def on_message(self, message: str | bytes) -> Future[None]:
        try:
            if isinstance(message, bytes):
                message = message.decode("utf-8")

            data = json.loads(message)
            content = data["content"]
            message_type = data["type"]  # 'command' or 'output'

            return self._check_mission(content, message_type)
        except Exception as e:
            logging.error(f"Error handling message: {e}")
            return Future()

    def _check_mission(self, content: str, message_type: str) -> Future[None]:
        if self.current_mission >= len(MISSIONS):
            return Future()

        mission = MISSIONS[self.current_mission]
        listener = mission["listener"]

        # Skip if message type doesn't match the target
        if listener["target"] != message_type:
            return Future()

        is_completed = False
        if listener["type"] == "regex":
            compiled_regex = regex.compile(listener["match"], regex.DOTALL)
            is_completed = bool(compiled_regex.search(content))
        elif listener["type"] == "exact":
            is_completed = content.strip() == listener["match"]

        if is_completed:
            self.current_mission += 1
            GradeManager.update(self.current_mission)
            return self._send_mission_complete()

        return Future()

    def _send_mission_complete(self) -> Future[None]:
        return self.write_message(
            {
                "type": "mission_complete",
                "currentMission": self.current_mission,
                "missions": MISSIONS,
            }
        )

    def on_close(self) -> None:
        MissionHandler.active_connections.remove(self)


class TermSocketWithLogging(TermSocket):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._current_input: list[str] = []
        self._output_buffer: list[str] = []
        self._flush_timeout = 0.2
        self._scheduled_flush: Optional[object] = None
        self._last_input = ""

    def on_message(self, message: str | bytes) -> Any:
        """Handle user input message"""
        try:
            if isinstance(message, str):
                data = json.loads(message)
                if data[0] == "stdin":
                    input_text = data[1]
                    if input_text == "\r":
                        command = "".join(self._current_input).strip()
                        if command:
                            if self._scheduled_flush:
                                IOLoop.current().remove_timeout(self._scheduled_flush)
                                self._flush_output_buffer()
                            logging.info(f"User Command: {command}")
                            IOLoop.current().add_callback(
                                self._notify_mission_handler,
                                {"type": "command", "content": command},
                            )
                        self._current_input = []
                    elif input_text in ("\b", "\x7f"):
                        if self._current_input:
                            self._current_input.pop()
                    else:
                        self._current_input.append(input_text)
                        self._last_input = input_text
        except Exception as e:
            logging.error(f"Error parsing terminal input: {e}")

        return super().on_message(message)

    def check_origin(self, origin: str) -> bool:
        return True

    def write_message(
        self, message: str | bytes | dict[str, Any], binary: bool = False
    ) -> Any:
        """Handle terminal output message"""
        try:
            if isinstance(message, str):
                data = json.loads(message)
                if data[0] in ["stdout", "stderr"]:
                    text = data[1]
                    # Clean control characters
                    clean_text = regex.sub(r"\x1b\[[0-9;]*[mK]", "", text)
                    clean_text = regex.sub(r"\x1b\[\?[0-9]+[hl]", "", clean_text)
                    clean_text = regex.sub(r"\r\n?", "\n", clean_text)
                    clean_text = clean_text.replace("\b", "")

                    # If the output is not the last input, the current input, or the
                    # last input, add it to the buffer
                    if (
                        clean_text.strip()
                        and clean_text.strip() != self._last_input
                        and clean_text.strip() != "".join(self._current_input)
                        and not clean_text.strip().endswith(self._last_input)
                    ):
                        self._output_buffer.append(clean_text)
                        self._schedule_flush()
        except Exception as e:
            logging.error(f"Error in write_message: {e}")

        return super().write_message(message, binary)

    def _schedule_flush(self) -> None:
        """Schedule flushing the output buffer"""
        if self._scheduled_flush:
            IOLoop.current().remove_timeout(self._scheduled_flush)
        self._scheduled_flush = IOLoop.current().call_later(
            self._flush_timeout, self._flush_output_buffer
        )

    def _flush_output_buffer(self) -> None:
        """Flush the output buffer"""
        self._scheduled_flush = None
        if self._output_buffer:
            output = "".join(self._output_buffer)
            if output:
                logging.info(f"Program Output: {output}")
                IOLoop.current().add_callback(
                    self._notify_mission_handler, {"type": "output", "content": output}
                )
            self._output_buffer = []

    def on_close(self):
        """Handle connection closure"""
        if self._scheduled_flush:
            IOLoop.current().remove_timeout(self._scheduled_flush)
        self._flush_output_buffer()
        logging.info("Terminal connection closed")
        super().on_close()

    def _notify_mission_handler(self, data: dict[str, Any]) -> None:
        """Notify all active mission handlers"""
        for handler in MissionHandler.active_connections:
            try:
                handler.on_message(json.dumps(data))
            except Exception as e:
                logging.error(f"Failed to notify mission handler: {e}")


def main():
    """Start the terminal server"""
    parser = argparse.ArgumentParser(description="Terminal server for checkpoint")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    parser.add_argument("--user", type=str, required=True, help="User to run as")
    parser.add_argument("--workdir", type=str, required=True, help="Working directory")
    args = parser.parse_args()

    # Wait for workspace directory to exist and set permissions
    # Note: PrairieLearn's behavior is to:
    # 1. Create and start the container
    # 2. Copy workspace files into the container's workdir
    # So we need to wait for the directory to exist before setting permissions
    max_attempts = 10  # Maximum number of attempts to wait
    attempt = 0
    while not os.path.exists(args.workdir) and attempt < max_attempts:
        print(
            f"Waiting for workspace directory to be created... "
            f"(attempt {attempt + 1}/{max_attempts})"
        )
        time.sleep(1)
        attempt += 1

    if not os.path.exists(args.workdir):
        print(
            f"Error: Workspace directory {args.workdir} was not created after "
            f"{max_attempts} seconds"
        )
    else:
        try:
            # Use subprocess to change ownership to the target user
            subprocess.run(
                ["chown", "-R", f"{args.user}:{args.user}", args.workdir], check=True
            )
            os.chmod(args.workdir, 0o700)  # rwx------
            print(
                f"Successfully set permissions for workspace directory: {args.workdir}"
            )
        except Exception as e:
            print(f"Failed to set workspace permissions: {e}")

    # Set grade directory based on workdir
    GradeManager.set_workdir(args.workdir)
    GradeManager.init()

    # Use program command from config
    program = PROGRAM_COMMAND

    # Prepare setup commands
    setup_script = " && ".join(SETUP_COMMANDS) if SETUP_COMMANDS else ""
    shell_command = f"cd {args.workdir}"
    if setup_script:
        shell_command += f" && {setup_script}"
    shell_command += f' && exec {" ".join(program)}'

    term_manager = UniqueTermManager(
        shell_command=["su", "-l", args.user, "--session-command", shell_command]
    )

    current_dir = os.path.dirname(os.path.abspath(__file__))

    settings = {"static_path": current_dir, "debug": True}

    app = Application(
        [
            (r"/terminals/(.*)", TermSocketWithLogging, {"term_manager": term_manager}),
            (r"/missions", MissionHandler),
            (
                r"/(.*)",
                StaticFileHandler,
                {"path": current_dir, "default_filename": "index.html"},
            ),
        ],
        None,
        None,
        **settings,
    )

    print(f"Server starting on port {args.port}...")
    app.listen(args.port, "0.0.0.0")
    IOLoop.current().start()


if __name__ == "__main__":
    main()
