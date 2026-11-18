# TOMORROW'S GUIDE — the merged kernel boot (the pinned-CI chain, ~20 min)

## STATE (all committed; the fork = dameriek-bit/ios-pipa)
- main = the apollo 0171-0186 merge (16 GPU/display/battery patches) + the Xcode 16.0 pin (commit 993828b)
- **The pinned CI build = GREEN**: run 44205694207, the artifact "xnu-kernel" = WAITING at
  https://github.com/dameriek-bit/ios-pipa/actions/runs/44205694207
- The touch patchers = byte-pattern-sensitive → the Xcode pin makes the new kernel's codegen match them
- The stable fallback build = shim/out/shim-boot.img AS IT IS NOW (payload 1a09df6d — no panic, touch good, wallpaper working)

## STEP 0 — back up the stable image (do not skip)
    cd /home/wsh/ios-pipa
    cp shim/out/shim-boot.img shim/out/shim-boot-stable.img
    cp shim/out/payload.bin shim/out/payload-stable.bin

## STEP 1 — download the merged kernel
    rm -rf /tmp/xnu-merged
    gh run download 44205694207 -R dameriek-bit/ios-pipa -n xnu-kernel -D /tmp/xnu-merged
    ls -la /tmp/xnu-merged/kernel.development.sweet   # ~18.6 MB

## STEP 2 — re-target the touch patchers (the symbols → the new addresses)
    python3 tools/retarget_touch.py xnu/out/kernel.development.sweet /tmp/xnu-merged/kernel.development.sweet
- Expect the deltas like: nvt_probe_id +0x24b0, SweetHIDTouch::touch +0x4e4c (they were exactly these on run 44203696709;
  the pinned rebuild = likely the same, but whatever prints is correct)
- This writes tools/patch_xnu_nt36532.retargeted.py + tools/patch_xnu_pipa_yflip.retargeted.py

## STEP 3 — patch the new kernel
    NVT_KERNEL=/tmp/xnu-merged/kernel.development.sweet python3 tools/patch_xnu_nt36532.retargeted.py
    python3 tools/patch_xnu_pipa_yflip.retargeted.py /tmp/xnu-merged/kernel.development.sweet.nop
- With the pinned Xcode the byte patterns SHOULD match (the assert errors = the old-codegen mismatch is gone).
- IF an assert still fails: the tool printed got/exp — decode both at that address, update the exp in the
  retargeted script, re-run. The patch_block asserts = safe (they abort before writing anything).

## STEP 4 — pack with the already-built device tree
    python3 tools/mkpayload.py /tmp/xnu-merged/kernel.development.sweet.nop.yf shim/out/pipa.adt shim/out/payload.bin \
      --cmdline 'debug=0xc serial=3 cpumask=0xf1 keepsyms=1 -noprogress rd=ufsroot0 ufsrw=1 rootrw=1 unentitled_ios_sim_launch=1 launchd_unsecure_cache=1 ignition_level=1 wdt=-1 wdt_test=no_user_checkin sweetfb_hz=60 sweetfb_native=1 sweetfb_fit=0 sweetfb_noconsole=1 sweetgpu=22 sweetgpukeep=1 sweetgpulevel=6 sweetgl_wait=300 sweetwifi=12 sweetbt=6 apollo_audio=5 sweettouch=1 sweettouchstage=4 sweettouchfw=1 sweettouchtlmm=0x0f500000 sweettouchrst=33 sweettouchirq=39 sweettouchbuf=0x125800 sweettouchdelay=0 sweettouchpoll=4 sweetinject=/usr/local/lib/libsweet-ca.dylib:backboardd sweetnull=backboardd,SpringBoard,mediaserverd'
    bash shim/build.sh ../shim/out/payload.bin

## STEP 5 — boot + test
    fastboot -S 512M flash userdata iphonex-root.simg   # ONLY if the root got damaged again
    fastboot boot shim/out/shim-boot.img
- Gestures: bottom-right swipe-up = Home, top-right swipe-down = Control Center
- Taps: Photos, Maps, the right column, corners
- GPU: the effects/blur/app animations (16 display/GPU patches are in this kernel, incl. surface-rows-64)

## ROLLBACK (30 s, nothing lost)
    fastboot boot shim/out/shim-boot-stable.img

## AFTER THE MERGED BOOT WORKS
- Auto-rotate stage 1: the landscape transpose (SweetFramebuffer present + SweetHID touch) — source-level, same CI route
- The left-half shear fix: also source-level now (the retarget tool makes ANY kernel patchable)
- GPU polish: need the user's specific symptoms
- Sound + the rest of the wallpapers: research/wallpaper/files-2.txt on any later boot

## THE BLOCKER FOUND (Nov 18, 04:5x): the compiler version
The merged kernel (run 44205694207) was built with a DIFFERENT Xcode than the Nov 3 kernel
(the runner image updated) → the instruction encodings at the touch patch sites differ →
the byte-pattern asserts fail (caught at the corner box 0xaee0a4, got fd7b41a9...).
The retarget-by-symbols WORKS (74+37 addresses computed correctly) — only the patterns break.

## THE FIRST COMMAND TOMORROW: get the Nov 3 build's exact Xcode
    gh api -H "Accept: application/vnd.github+json" \
      /repos/nishant713/ios-pipa/actions/runs/41685645418/logs > /tmp/nov3-logs.zip
    python3 - <<'PY'
    import zipfile, re
    z = zipfile.ZipFile('/tmp/nov3-logs.zip')
    for name in z.namelist():
        if 'build' not in name.lower(): continue
        for m in re.findall(r'/Applications/Xcode[_0-9.]+\.app', z.read(name).decode(errors='replace')):
            print(m)
    PY
(NOTE: the run is on nishant713/ios-pipa, NOT the fork — the first attempt 404'd because the fork was used.)
Then: pin THAT Xcode in .github/workflows/xnu.yml (the pin step exists — change 16.0 to the found
version), push, dispatch, and run the SAME chain from STEP 1 of this guide. Same compiler = the same
bytes = the patterns match = the patchers work as-is.
