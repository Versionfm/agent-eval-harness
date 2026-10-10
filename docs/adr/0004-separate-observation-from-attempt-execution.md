# Separate observation and playback from attempt execution

The first viewer observes CLI-launched attempts and plays back recorded evidence; its controls change playback rather than start, pause or resume an agent. We accept a less integrated operator experience to make harness behavior inspectable without giving the UI ownership of model requests, repository tools or attempt lifecycle. Execution controls and resumable agent state require a separate design rather than reusing playback controls.
