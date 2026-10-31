"""Give a disposable Chromium child its pipe descriptors, without preexec in HTTP threads."""
import os
import sys

if __name__ == '__main__':
    executable, read_fd, write_fd, profile = sys.argv[1:]
    # Duplicate first: a source descriptor may itself be 3 or 4.
    read_copy, write_copy = os.dup(int(read_fd)), os.dup(int(write_fd))
    os.dup2(read_copy, 3, inheritable=True)
    os.dup2(write_copy, 4, inheritable=True)
    os.set_inheritable(3, True)
    os.set_inheritable(4, True)
    for fd in {int(read_fd), int(write_fd), read_copy, write_copy} - {3, 4}:
        os.close(fd)
    os.execv(executable, [executable, '--headless=new', '--remote-debugging-pipe',
                         '--user-data-dir='+profile, '--no-first-run', '--no-default-browser-check',
                         '--disable-background-networking', 'about:blank'])
