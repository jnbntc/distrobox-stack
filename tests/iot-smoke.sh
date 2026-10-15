#!/usr/bin/env bash
set -euo pipefail

# Run inside the image as an ordinary UID, with --network=none and NO devices.
test "$(id -u)" -ne 0
test_dir="$(mktemp -d /tmp/iot-smoke.XXXXXX)"
trap 'rm -rf "$test_dir"' EXIT
export HOME="$test_dir/home"
export XDG_DATA_HOME="$test_dir/xdg"
export CCACHE_DIR="$test_dir/ccache"
export PLATFORMIO_SETTING_ENABLE_TELEMETRY=no
unset PLATFORMIO_CORE_DIR
mkdir -p "$HOME" "$XDG_DATA_HOME"

check_pio() {
    pio --version | grep -Fx 'PlatformIO Core, version 6.2.0'
    platformio --version | grep -Fx 'PlatformIO Core, version 6.2.0'
    pio system info
    pio device list
    pio pkg list -g
    /opt/pio/bin/python -m pip check
    test -d "$XDG_DATA_HOME/platformio"
    test ! -e "$HOME/.platformio"
    test "$(/opt/pio/bin/python -c 'import sys; print(sys.prefix)')" = /opt/pio
}

command -v lsusb
command -v udevadm
check_pio
test ! -w /opt/pio
test ! -w /opt/esp
test "$(git -C /opt/esp/idf rev-parse HEAD)" = b774170ff46c393eeb5e495ea37936038d3f4f4f
idf-env idf.py --version | grep -Fx 'ESP-IDF v5.5.5'
idf-env bash -euo pipefail -c '
    test "$(command -v python)" = /opt/esp/python/bin/python
    python -m pip check
    cmake --version
    ninja --version
    xtensa-esp-elf-gcc --version
    riscv32-esp-elf-gcc --version
    pio --version | grep -Fx "PlatformIO Core, version 6.2.0"
    pio system info
    pio device list
    pio pkg list -g
'

# Compile the upstream FreeRTOS hello_world. No InfraBadge firmware or board GPIOs.
cp -R /opt/esp/idf/examples/get-started/hello_world "$test_dir/hello_world"
cd "$test_dir/hello_world"
idf-env idf.py set-target esp32s3
idf-env idf.py build
test -s build/hello_world.bin
test -s build/bootloader/bootloader.bin
grep -Fx 'CONFIG_IDF_TARGET="esp32s3"' sdkconfig
idf-env python -c 'from elftools.elf.elffile import ELFFile; f = open("build/hello_world.elf", "rb"); assert ELFFile(f).header.e_machine == "EM_XTENSA"'
check_pio
printf '%s\n' 'PASS: ESP32-S3 build and PlatformIO smoke tests (offline, unprivileged, no hardware).'
