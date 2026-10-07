from pathlib import Path
import os
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
SCRIPT=Path(os.environ.get('SWIFTVLC_BUILD_SCRIPT', ROOT/'scripts/build-libvlc.sh'))


class DeviceBuildLaneTests(unittest.TestCase):
    def plan(self,*flags):
        s=SCRIPT.read_text()
        defaults=s[s.index('BUILD_IOS=yes\n'):s.index('# libVLC run-time assertions')]
        parse=s[s.index('for arg in "$@"; do',s.index('# --- Parse arguments ---')):s.index('\nif [ "${CLEAN_ONLY}"')]
        start=s.index('if [ "$BUILD_IOS" = "yes" ]; then',s.index('XCFRAMEWORK_ARGS=()'))
        ios=s[start:s.index('\nif [ "$BUILD_TVOS" = "yes" ]; then',start)]
        with tempfile.TemporaryDirectory(prefix='swiftvlc-build-plan-') as d:
            pre='''set -e
BUILD_DIR="$1"; shift
VLC_SRC="$BUILD_DIR"; NATIVE_BUILD_DIRECTORY="$BUILD_DIR"; REPO_ROOT="$BUILD_DIR"
compile_libvlc() { echo "compile:$1:$2"; local arch="$1"; [ "$arch" = aarch64 ] && arch=arm64; mkdir -p "$VLC_SRC/build-$2-$arch/static-lib"; touch "$VLC_SRC/build-$2-$arch/static-lib/libvlc-full-static.a"; }
lipo() { echo "lipo"; while [ "$1" != -output ]; do shift; done; touch "$2"; }
info() { :; }
'''
            body=pre+defaults+parse+'\nXCFRAMEWORK_ARGS=()\n'+ios+'\necho "slices:${#XCFRAMEWORK_ARGS[@]}"\necho "tvos:$BUILD_TVOS"\n'
            return subprocess.check_output(['bash','-c',body,'build-plan',d,*flags],text=True)
    def test_device_only_build_has_no_simulator(self):
        p=self.plan('--ios-device-only')
        self.assertEqual(p.splitlines(),['compile:aarch64:iphoneos','slices:4','tvos:no'])
    def test_default_still_builds_all_three_ios_architectures(self):
        p=self.plan()
        self.assertIn('compile:aarch64:iphonesimulator',p);self.assertIn('compile:x86_64:iphonesimulator',p)
        self.assertIn('slices:8',p)
    def test_later_ios_and_all_options_restore_simulators(self):
        for flag in ['--ios-only','--all']:
            p=self.plan('--ios-device-only',flag)
            self.assertIn('compile:x86_64:iphonesimulator',p);self.assertIn('slices:8',p)
if __name__=='__main__': unittest.main()
