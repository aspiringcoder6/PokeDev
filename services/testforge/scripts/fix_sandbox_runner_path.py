
path = r'D:\VTS\sandbox-kit\broker\services\sandbox_provisioner.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

bad = '"executor", "dist", "container_runner_linux", "container_runner_linux"'
good = '"executor", "dist", "container_runner_linux"'

if bad in content:
    new_content = content.replace(bad, good, 1)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("SUCCESS: Fixed RUNNER_BINARY path in sandbox_provisioner.py")
else:
    print("WARNING: Target string not found. Content may already be fixed.")
