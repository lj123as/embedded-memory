# Installing Embedded Memory for OpenCode

## Installation Steps

```bash
git clone https://github.com/<OWNER>/<REPO>.git ~/.config/opencode/embedded-memory
ln -s ~/.config/opencode/embedded-memory/.opencode/plugin.json ~/.config/opencode/plugins/embedded_memory.json
```

Restart OpenCode, then discover skills:

```text
find_skills embedded_memory
use_skill embedded_memory:using_embedded_memory
```

