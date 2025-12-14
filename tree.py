# TOOLS/tree.py
import os

# Folders to ignore
IGNORE = {".git", ".venv", "__pycache__", "node_modules"}

def print_tree(start_path: str, prefix: str = ""):
    try:
        entries = sorted(os.listdir(start_path))
    except PermissionError:
        return

    # Filter ignored folders
    entries = [e for e in entries if e not in IGNORE]

    for i, entry in enumerate(entries):
        path = os.path.join(start_path, entry)
        connector = "└── " if i == len(entries) - 1 else "├── "
        print(prefix + connector + entry)
        if os.path.isdir(path):
            extension = "    " if i == len(entries) - 1 else "│   "
            print_tree(path, prefix + extension)

if __name__ == "__main__":
    root = "."  # current folder
    print(root)
    print_tree(root)
