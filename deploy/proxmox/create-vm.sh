#!/usr/bin/env bash
set -Eeuo pipefail
echo 'Dotychczasowy instalator VM zostal zastapiony pelna instalacja w LXC.'
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/install-lxc.sh" "$@"
