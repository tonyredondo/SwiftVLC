"""Compile the exact native probe helper; verify silence, bounded logs and unchanged cue values."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get('SWIFTVLC_TIMING_SOURCE', ROOT / 'scripts/patches/0055-subtitle-timing-diagnostics.patch'))


class SubtitleTimingProbeTests(unittest.TestCase):
    def test_exact_c_helper(self):
        text=SOURCE.read_text()
        if SOURCE.suffix == '.patch':
            text=''.join(line[1:] for line in text.splitlines(True) if line.startswith('+') and not line.startswith('+++'))
        start=text.index('static void\nspu_TraceSubtitleTiming(')
        helper=text[start:text.index('\n}\n',start)+3]
        preamble=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#define VLC_TICK_FROM_SEC(n) ((int64_t)(n)*1000000)
#define VLC_TICK_INVALID INT64_MIN
typedef int64_t vlc_tick_t;
typedef struct { bool b_subtitle, b_ephemer; int i_channel; int64_t i_order, i_start, i_stop; } subpicture_t;
typedef struct { subpicture_t *subpic; int64_t orgstart,orgstop,start,stop; bool is_late; int timing_state; int64_t timing_last_log; } spu_render_entry_t;
struct spu_channel { void *clock; float rate; int64_t delay; };
typedef struct { int spu; bool subtitle_timing_enabled; } spu_private_t;
static int count;
static char line[1024];
static void capture(void *spu, const char *format, ...) {
 (void)spu; va_list args; va_start(args,format);
 int n=vsnprintf(line,sizeof(line),format,args); va_end(args);
 assert(n>0 && (size_t)n<sizeof(line)); count++;
}
#define msg_Info capture
'''
        cases=r'''
int main(void) {
 spu_private_t sys={0};
 struct spu_channel channel={.clock=&sys,.rate=1,.delay=0};
 subpicture_t pic={.b_subtitle=true,.i_channel=3,.i_order=100,.i_start=9000000,.i_stop=12000000};
 spu_render_entry_t entry={.subpic=&pic,.orgstart=20000000,.orgstop=23000000,.start=9000000,.stop=12000000,.timing_state=-1,.timing_last_log=VLC_TICK_INVALID};
 spu_render_entry_t original=entry;
 spu_TraceSubtitleTiming(&sys,&channel,&entry,2,10000000,10000000,9000000);
 assert(count==0 && memcmp(&entry,&original,sizeof(entry))==0);
 sys.subtitle_timing_enabled=true; pic.b_subtitle=false;
 spu_TraceSubtitleTiming(&sys,&channel,&entry,2,10000000,10000000,9000000);
 assert(count==0); pic.b_subtitle=true;
 spu_TraceSubtitleTiming(&sys,&channel,&entry,2,10000000,10000000,9000000);
 assert(count==1);
 assert(strcmp(line,"SWIFTVLC_SPU_V1 event=2 channel=3 order=100 now=10000000 render=10000000 org_start=20000000 org_stop=23000000 start=9000000 stop=12000000 pic_start=9000000 pic_stop=12000000 boundary=9000000 rate_ppm=1000000 delay=0 flags=4")==0);
 for(int i=1;i<60;i++) spu_TraceSubtitleTiming(&sys,&channel,&entry,2,10000000+i*10000,10000000,9000000);
 assert(count==1);
 spu_TraceSubtitleTiming(&sys,&channel,&entry,2,11000000,11000000,9000000); assert(count==2);
 spu_TraceSubtitleTiming(&sys,&channel,&entry,3,11001000,11001000,12000000); assert(count==3);
 spu_TraceSubtitleTiming(&sys,NULL,&entry,4,11002000,VLC_TICK_INVALID,VLC_TICK_INVALID); assert(count==4);
 assert(strstr(line,"render=-9223372036854775808")!=NULL);
 spu_TraceSubtitleTiming(&sys,&channel,&entry,4,5000000,5000000,9000000); assert(count==5);
 // Probe fields are the only mutable state; native cue dates and flags remain exact.
 entry.timing_state=original.timing_state; entry.timing_last_log=original.timing_last_log;
 assert(memcmp(&entry,&original,sizeof(entry))==0);
 assert(pic.i_start==9000000 && pic.i_stop==12000000 && pic.i_order==100);
 puts("PASS native subtitle probe: disabled silence; OSD exclusion; numeric protocol; 1Hz steady states; immediate transitions; immutable cue times");
}
'''
        with tempfile.TemporaryDirectory(prefix='swiftvlc-timing-') as d:
            p=Path(d);(p/'probe.c').write_text(preamble+helper+cases)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'probe.c'),'-o',str(p/'probe')],check=True)
            subprocess.run([str(p/'probe')],check=True)
if __name__=='__main__': unittest.main()
