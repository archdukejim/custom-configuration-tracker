import os

_EXT_MAP: dict[str, str] = {
    ".py":         "python",
    ".js":         "javascript",
    ".ts":         "typescript",
    ".jsx":        "jsx",
    ".tsx":        "tsx",
    ".json":       "json",
    ".yaml":       "yaml",
    ".yml":        "yaml",
    ".toml":       "toml",
    ".sh":         "bash",
    ".bash":       "bash",
    ".zsh":        "bash",
    ".fish":       "bash",
    ".conf":       "nginx",
    ".cfg":        "ini",
    ".ini":        "ini",
    ".env":        "bash",
    ".xml":        "xml",
    ".html":       "html",
    ".htm":        "html",
    ".css":        "css",
    ".scss":       "scss",
    ".sql":        "sql",
    ".rb":         "ruby",
    ".go":         "go",
    ".rs":         "rust",
    ".java":       "java",
    ".c":          "c",
    ".h":          "c",
    ".cpp":        "cpp",
    ".hpp":        "cpp",
    ".cs":         "csharp",
    ".php":        "php",
    ".tf":         "hcl",
    ".hcl":        "hcl",
    ".lua":        "lua",
    ".pl":         "perl",
    ".pm":         "perl",
    ".md":         "markdown",
    ".service":    "ini",
    ".timer":      "ini",
    ".socket":     "ini",
}

_BASENAME_MAP: dict[str, str] = {
    "dockerfile":           "docker",
    "containerfile":        "docker",
    "makefile":             "makefile",
    "vagrantfile":          "ruby",
    "gemfile":              "ruby",
    "nginx.conf":           "nginx",
    "nginx":                "nginx",
    "httpd.conf":           "apacheconf",
    "apache2.conf":         "apacheconf",
    "sshd_config":          "bash",
    "ssh_config":           "bash",
    "known_hosts":          "bash",
    "authorized_keys":      "bash",
    "fstab":                "bash",
    "crypttab":             "bash",
    "passwd":               "bash",
    "group":                "bash",
    "shadow":               "bash",
    "hosts":                "bash",
    "hostname":             "bash",
    "resolv.conf":          "bash",
    "nsswitch.conf":        "bash",
    "sudoers":              "bash",
    ".bashrc":              "bash",
    ".bash_profile":        "bash",
    ".profile":             "bash",
    ".zshrc":               "bash",
    ".vimrc":               "vim",
    ".tmux.conf":           "bash",
    ".gitconfig":           "ini",
    ".gitignore":           "git",
    "requirements.txt":     "none",
    "pyproject.toml":       "toml",
    "setup.cfg":            "ini",
    "package.json":         "json",
    "tsconfig.json":        "json",
    "docker-compose.yml":   "yaml",
    "docker-compose.yaml":  "yaml",
    ".env":                 "bash",
    ".env.local":           "bash",
    ".env.example":         "bash",
    "crontab":              "bash",
    "grub.cfg":             "bash",
    "grub.conf":            "bash",
}


def detect_language(file_path: str) -> str:
    """Return a Prism.js language identifier for the given file path.

    Lookup order:
      1. Exact basename match (case-insensitive)
      2. File extension match (case-insensitive)
      3. Fall back to 'none' (plain text)
    """
    basename = os.path.basename(file_path).lower()
    if basename in _BASENAME_MAP:
        return _BASENAME_MAP[basename]
    _, ext = os.path.splitext(basename)
    return _EXT_MAP.get(ext, "none")
