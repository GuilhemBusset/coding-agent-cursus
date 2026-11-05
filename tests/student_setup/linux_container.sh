#!/usr/bin/env bash
# CI (student-setup.yml): inside a clean container from a pinned image, as root. Adds only what
# the one-liner itself needs (curl and CA certificates) and a non-root user with sudo, then runs
# run_twice.sh as that user. The installer installs everything else.
#
#   docker run --rm -v "$PWD:/src:ro" -e PREP="<package command>" IMAGE bash /src/tests/student_setup/linux_container.sh
set -euo pipefail

echo "::group::prepare the container: $PREP"
eval "$PREP"
command -v useradd >/dev/null
useradd -m -s /bin/bash student
echo 'student ALL=(ALL) NOPASSWD:ALL' >/etc/sudoers.d/student
chmod 440 /etc/sudoers.d/student
# A copy the user owns, so git accepts it as a clone source (safe.directory).
cp -a /src /home/student/src
chown -R student: /home/student/src
echo "::endgroup::"

for tool in git gh uv mise claude codex; do
  if command -v "$tool" >/dev/null 2>&1; then echo "Before the setup, $tool is already installed: $(command -v "$tool")"; fi
done
sudo -u student -H bash /home/student/src/tests/student_setup/run_twice.sh /home/student/src
