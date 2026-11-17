#!/bin/bash
# Bake ALL pipa fixes into the existing root image once (then flash it):
#   sudo bash tools/bake-pipa-root.sh [IMG]      (default: iphonex-root.img)
# After this, the boot image no longer injects these files every boot
# (datamigrator's completed state is never clobbered again).
set -euo pipefail
cd "$(dirname "$0")/.."
IMG=${1:-iphonex-root.img}
MNT=/mnt/ipadroot
[[ -f $IMG ]] || { echo "no $IMG"; exit 1; }
command -v img2simg >/dev/null || { echo "install img2simg"; exit 1; }

fsck.hfsplus -fy "$IMG"
mkdir -p "$MNT"
mountpoint -q "$MNT" && umount "$MNT"
mount -t hfsplus -o loop,force "$IMG" "$MNT"

echo "== pipa tweaks (build 20G81)"
python3 tools/pipa-root-tweaks.py "$MNT"

echo "== migration-done stamps (20G81)"
for dst in private/var/mobile/Library/Preferences private/var/root/Library/Preferences; do
  install -d -m 0755 "$MNT/$dst"
  install -m 0600 tools/root-files/migration-done.plist "$MNT/$dst/com.apple.migration.plist"
done
U=CFD063D6-B9D4-524D-B2ED-2805B3617885
for dst in private/var/mobile/Library/Preferences/ByHost private/var/root/Library/Preferences/ByHost; do
  install -d -m 0755 "$MNT/$dst"
  for u in "$U" "${U,,}"; do
    install -m 0600 tools/root-files/migration-done-host.plist "$MNT/$dst/com.apple.migration.$u.plist"
  done
done

echo "== sweet userland libraries -> /usr/local/lib"
install -d -m 0755 "$MNT/usr/local/lib"
for f in sweet-userland/lib/libsweet-ca.dylib sweet-userland/lib/libsweet-gl.dylib \
         sweet-userland/lib/libsweet-fix.dylib sweet-userland/lib/libOSMesa.8.dylib \
         sweet-bt/lib/libsweet-bt.dylib; do
  install -m 0755 "$f" "$MNT/usr/local/lib/$(basename "$f")"
done

echo "== HakiosAudio HAL driver + VirtualAudio back (boot-64 final state)"
install -d -m 0755 "$MNT/System/Library/Audio/Plug-Ins/HAL/HakiosAudio.driver"
install -m 0755 sweet-audio/HakiosAudio.driver/HakiosAudio "$MNT/System/Library/Audio/Plug-Ins/HAL/HakiosAudio.driver/"
install -m 0644 sweet-audio/HakiosAudio.driver/Info.plist "$MNT/System/Library/Audio/Plug-Ins/HAL/HakiosAudio.driver/"
if [ -d "$MNT/Library/Audio/Plug-Ins/HAL.disabled/VirtualAudio.plugin" ] && [ ! -e "$MNT/Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin" ]; then
  mv "$MNT/Library/Audio/Plug-Ins/HAL.disabled/VirtualAudio.plugin" "$MNT/Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin"
  echo "VirtualAudio.plugin moved back to HAL/"
fi

echo "== launchd disabled.plist: quiet set, Bluetooth ENABLED"
install -d -m 0755 "$MNT/private/var/db/com.apple.xpc.launchd"
install -m 0644 tools/root-files/launchd-disabled-quiet-bt.plist "$MNT/private/var/db/com.apple.xpc.launchd/disabled.plist"

echo "== SweetMetal2.bundle -> /System/Library/Extensions"
install -d -m 0755 "$MNT/System/Library/Extensions/SweetMetal2.bundle/_CodeSignature"
install -m 0755 sweet-metal2/SweetMetal2.bundle/HotMetal2 "$MNT/System/Library/Extensions/SweetMetal2.bundle/"
install -m 0755 sweet-metal2/SweetMetal2.bundle/libvulkan_freedreno.dylib "$MNT/System/Library/Extensions/SweetMetal2.bundle/"
install -m 0644 sweet-metal2/SweetMetal2.bundle/Info.plist "$MNT/System/Library/Extensions/SweetMetal2.bundle/"
install -m 0644 sweet-metal2/SweetMetal2.bundle/_CodeSignature/CodeResources "$MNT/System/Library/Extensions/SweetMetal2.bundle/_CodeSignature/"

umount "$MNT"
fsck.hfsplus -fy "$IMG"
rm -f iphonex-root.simg
img2simg "$IMG" iphonex-root.simg
echo "DONE: flash with  fastboot -S 512M flash userdata iphonex-root.simg"
