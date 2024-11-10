# Checkpoint

Checkpoint helps you create step-by-step, mission-based tutorials in PrairieLearn. Students learn through hands-on practice in a terminal environment, receiving instant feedback as they progress through each mission. Unlike traditional tutorials, Checkpoint actively monitors student progress and provides immediate validation when they successfully complete each step.

## Quick Start

Let's dive into an interactive Git tutorial! We've created a hands-on learning experience where students start with the basics of version control. They'll begin by initializing their first Git repository, then learn about staging files and making commits. As they type commands in the terminal, they'll receive instant feedback confirming they're on the right track, making it easy to progress through each mission at their own pace.

To get started, install the package:

```bash
pip install -e .
```

Before deploying the question, make sure you're logged into Docker Hub since we'll need to push some images:

```bash
docker login
```

Take a look at `examples/questions/git-tutorial/checkpoint.yaml` - this single file defines our entire Git tutorial. It specifies what commands students will learn, how to validate their progress, and what feedback they'll receive. The YAML format makes it easy to understand and modify the tutorial structure.

Ready to try it out? Let's deploy the tutorial:

```bash
cd examples/questions/git-tutorial
checkpoint deploy
```

This command does all the heavy lifting for you. It builds a Docker image with Git and all the necessary tools, pushes it to Docker Hub, and generates the PrairieLearn question files. You'll see several new files appear - these are what make the interactive tutorial work in PrairieLearn.

Time to fire up PrairieLearn! This command comes from their [official documentation](https://prairielearn.readthedocs.io/en/latest/installing/#running-docker-with-the-extended-features):

```bash
cd ../../.. # Move to the root of the Checkpoint repo
docker run -it --rm -p 3000:3000 -v "${PWD}/examples:/course" -v "${PWD}/examples/pl_ag_jobs:/jobs" -e HOST_JOBS_DIR="${PWD}/examples/pl_ag_jobs" -v /var/run/docker.sock:/var/run/docker.sock --platform linux/amd64 --add-host=host.docker.internal:172.17.0.1 prairielearn/prairielearn
```

Once PrairieLearn is running, open http://localhost:3000 in your browser. Click the green "Load from Disk" button in the top-right corner, then head back to the homepage. Look for "PL Active Environment Runtime" under "Courses with instructor access", click it, and you'll find the Git tutorial in the Questions panel.

## Create Your Own Tutorial

Want to create your own tutorial? Take a look at `examples/questions/git-tutorial/checkpoint.yaml`. This single file defines everything about the tutorial - what Docker image to use, what packages to install, and what missions students need to complete. When you run `checkpoint deploy`, it transforms this YAML file into all the necessary PrairieLearn components.

## License

MIT