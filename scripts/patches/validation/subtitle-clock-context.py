"""Replay the real pinned clock and SPU conversions with captured cue timing.

The clock math and queue call sites come directly from the native source. Locks
are stubbed for this single-threaded numerical test; native build and physical
player qualification provide separate integration evidence.
"""

from pathlib import Path
import argparse, re, subprocess, tempfile


def function(text, name):
    m = re.search(r"\b" + re.escape(name) + r"\([^;]+?\)\s*\{", text)
    assert m, name
    start = text.rfind("\n\n", 0, m.start()) + 2
    i = text.index("{", m.start())
    depth = 1
    j = i + 1
    while depth:
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
        j += 1
    return text[start:j] + "\n"


PRE = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <inttypes.h>
#include <limits.h>
#define VLC_TICK_INVALID 0
#define VLC_TICK_MAX INT64_MAX
#define VLC_TICK_FROM_SEC(s) ((int64_t)(s)*1000000)
#define VOUT_SPU_CHANNEL_OSD_COUNT 2
#define AssertLocked(c) ((void)(c))
/* Numeric collector has its own sanitizer/privacy test. */
#define vlc_clock_TimingTrace(...) ((void)0)
#define __MAX(a,b) ((a)>(b)?(a):(b))
#define vlc_error(logger,...) ((void)(logger))
static inline void *vlc_reallocarray(void *p,size_t n,size_t s) { assert(!s||n<=SIZE_MAX/s);return realloc(p,n*s); }
#include "vlc_list.h"
#include "vlc_vector.h"
typedef int64_t vlc_tick_t;
typedef struct { vlc_tick_t system,stream; } clock_point_t;
static inline clock_point_t clock_point_Create(vlc_tick_t system,vlc_tick_t stream) { return (clock_point_t){system,stream}; }
#define MAX_PCR_DELAY VLC_TICK_FROM_SEC(60)
typedef struct vlc_clock_context { double rate,coeff;vlc_tick_t offset;uint32_t clock_id;clock_point_t last,start_time,wait_sync_ref;struct vlc_list node; } ctx_t;
typedef struct vlc_clock_t vlc_clock_t;
typedef struct vlc_clock_main_t { vlc_clock_t *master;ctx_t *context;struct vlc_list prev_contexts;vlc_tick_t delay,pause_date,output_dejitter,input_dejitter;bool paused;unsigned wait_sync_ref_priority;clock_point_t first_pcr;void *logger; } vlc_clock_main_t;
struct vlc_clock_ops { vlc_tick_t (*to_system)(vlc_clock_t *,ctx_t *,vlc_tick_t,vlc_tick_t,double); };
struct vlc_clock_t { const struct vlc_clock_ops *ops;vlc_clock_main_t *owner;ctx_t *context;vlc_tick_t last_conversion,delay;unsigned priority;bool follow_output_timeline; };
static void vlc_clock_switch_context(vlc_clock_t *c,ctx_t *ctx) { (void)c;(void)ctx;abort(); } // All call sites under test use update=false.
static void vlc_clock_Lock(vlc_clock_t *c) { (void)c; }
static void vlc_clock_Unlock(vlc_clock_t *c) { (void)c; }
typedef struct { int64_t i_channel;vlc_tick_t i_start,i_stop; } subpicture_t;
typedef struct { subpicture_t *subpic;vlc_tick_t orgstart,orgstop,start,stop; } spu_render_entry_t;
struct spu_channel { vlc_clock_t *clock;double rate;struct VLC_VECTOR(spu_render_entry_t) entries; };
"""
CASES = r"""
static void setup(ctx_t *old,ctx_t *current,vlc_clock_main_t *main,vlc_clock_t *clock) {
 *old=(ctx_t){.rate=1,.coeff=1,.offset=750275163950LL,.clock_id=0,.last={.system=1}};
 *current=*old;current->offset=750274415929LL;current->clock_id=1;
 *main=(vlc_clock_main_t){.context=current,.wait_sync_ref_priority=UINT_MAX};vlc_list_init(&main->prev_contexts);vlc_list_append(&old->node,&main->prev_contexts);
 static const struct vlc_clock_ops ops={.to_system=vlc_clock_slave_to_system};
 *clock=(vlc_clock_t){.ops=&ops,.owner=main,.context=old,.last_conversion=751678708931LL};
}

/* These origins mirror VLC's contexts_run discontinuity contract: the old
 * output remains buffered while a new PCR origin is already available. */
static bool mixed_timeline_queue(void) {
 static const struct {
  const char *name;
  double rate;
  vlc_tick_t old_offset,new_offset;
  vlc_tick_t old_start,old_stop,new_start,new_stop;
  vlc_tick_t want_old_start,want_old_stop,want_new_start,want_new_stop;
 } cases[] = {
  {"forward PCR jump",1,1000000,-28900000,
   10001,50001,30000000,30100000,1010001,1050001,1100000,1200000},
  {"backward PCR jump",1,-29000000,1100000,
   30010001,30050001,1,100001,1010001,1050001,1100001,1200001},
  {"forward PCR jump at2x",2,1000000,-13900000,
   10002,50002,30000000,30100000,1005001,1025001,1100000,1150000},
 };
 for(size_t c=0;c<sizeof(cases)/sizeof(cases[0]);c++) {
  for(int reversed=0;reversed<2;reversed++) {
   ctx_t old={.rate=cases[c].rate,.coeff=1,.offset=cases[c].old_offset,.clock_id=0,.last={.system=1}};
   ctx_t current=old;current.offset=cases[c].new_offset;current.clock_id=1;
   vlc_clock_main_t owner={.context=&current,.wait_sync_ref_priority=UINT_MAX};
   vlc_list_init(&owner.prev_contexts);vlc_list_append(&old.node,&owner.prev_contexts);
   static const struct vlc_clock_ops ops={.to_system=vlc_clock_slave_to_system};
   vlc_clock_t clock={.ops=&ops,.owner=&owner,.context=&old,.last_conversion=1000001};
   subpicture_t pics[2]={{.i_channel=3},{.i_channel=3}};
   spu_render_entry_t entries[2]={
    {.subpic=&pics[0],.orgstart=cases[c].old_start,.orgstop=cases[c].old_stop},
    {.subpic=&pics[1],.orgstart=cases[c].new_start,.orgstop=cases[c].new_stop}};
   if(reversed) {spu_render_entry_t tmp=entries[0];entries[0]=entries[1];entries[1]=tmp;}
   struct spu_channel channel={.clock=&clock,.rate=cases[c].rate,.entries={.data=entries,.size=2,.cap=2}};
   assert(spu_channel_UpdateDates(&channel,1100000)==2);
   const spu_render_entry_t *older=&entries[reversed?1:0],*newer=&entries[reversed?0:1];
   if(older->start!=cases[c].want_old_start || older->stop!=cases[c].want_old_stop
      || newer->start!=cases[c].want_new_start || newer->stop!=cases[c].want_new_stop) {
    fprintf(stderr,"FAIL %s queue_order=%d: old=%"PRId64"..%"PRId64" new=%"PRId64"..%"PRId64" expected old=%"PRId64"..%"PRId64" new=%"PRId64"..%"PRId64"\n",
      cases[c].name,reversed,older->start,older->stop,newer->start,newer->stop,
      cases[c].want_old_start,cases[c].want_old_stop,cases[c].want_new_start,cases[c].want_new_stop);
    return false;
   }
   /* Enqueueing either epoch is lookahead, so it must leave playback untouched. */
   const vlc_tick_t reference=clock.last_conversion;
   subpicture_t older_queued={.i_start=cases[c].old_start,.i_stop=cases[c].old_stop};
   subpicture_t newer_queued={.i_start=cases[c].new_start,.i_stop=cases[c].new_stop};
   queue_dates(&channel,&older_queued,1100000);
   queue_dates(&channel,&newer_queued,1100000);
   assert(older_queued.i_start==cases[c].want_old_start && older_queued.i_stop==cases[c].want_old_stop);
   assert(newer_queued.i_start==cases[c].want_new_start && newer_queued.i_stop==cases[c].want_new_stop);
   assert(clock.last_conversion==reference);
   /* Looking ahead must not attach the output to a new context or retire the old one. */
   assert(clock.context==&old && !vlc_list_is_empty(&owner.prev_contexts));
  }
 }
 puts("PASS mixed timelines: forward/backward PCR jumps,2x rate,both queue orders");
 return true;
}

/* Captured failure: continuous master output, a newer PCR fallback origin,
 * then a normal 3.65s dialogue gap. Cue spacing must not choose a new epoch. */
static bool continuous_dialogue_gap(void) {
 static const struct vlc_clock_ops ops={.to_system=vlc_clock_slave_to_system};
 ctx_t old={.rate=1,.coeff=1,.offset=1000000,.clock_id=0,
            .last={.system=5650001,.stream=4650001}};
 ctx_t current={.rate=1,.coeff=1,.clock_id=1,
               .wait_sync_ref={.system=1400001,.stream=1000001}};
 vlc_clock_main_t owner={.context=&current,.wait_sync_ref_priority=0};
 vlc_list_init(&owner.prev_contexts);vlc_list_append(&old.node,&owner.prev_contexts);
 vlc_clock_t audio={.ops=&ops,.owner=&owner,.context=&old};
 owner.master=&audio;
 vlc_clock_t clock={.ops=&ops,.owner=&owner,.context=&old,.last_conversion=2000001,.follow_output_timeline=true};
 subpicture_t pic={.i_channel=3};
 spu_render_entry_t entry={.subpic=&pic,.orgstart=4650001,.orgstop=5650001};
 struct spu_channel channel={.clock=&clock,.rate=1,.entries={.data=&entry,.size=1,.cap=1}};
 assert(spu_channel_UpdateDates(&channel,5650001)==1);
 if(entry.start!=5650001 || entry.stop!=6650001) {
  fprintf(stderr,"FAIL continuous dialogue gap: expected5650001..6650001,got%"PRId64"..%"PRId64"\n",entry.start,entry.stop);
  return false;
 }
 /* A real output transition must change the external subtitle timeline too.
  * This is per-output anchoring, not freezing one context for the track. */
 audio.context=&current;
 current.last=(clock_point_t){.system=6050001,.stream=4650001};
 current.offset=1400000;
 assert(spu_channel_UpdateDates(&channel,6050001)==1);
 if(entry.start!=6050001 || entry.stop!=7050001) {
  fprintf(stderr,"FAIL external subtitle did not follow actual output transition\n");return false;
 }
 puts("PASS external subtitles: normal dialogue gap and actual output transition");
 return true;
}

/* A real jump must still use the newer PCR origin before its first output
 * update. Queued subtitles can span both timelines during that transition. */
static bool pending_pcr_timelines(void) {
 static const struct vlc_clock_ops ops={.to_system=vlc_clock_slave_to_system};
 for(int backward=0;backward<2;backward++) {
  vlc_tick_t old_pts=backward?30000001:1,new_pts=backward?1:30000000;
  ctx_t old={.rate=1,.coeff=1,.offset=1000000-old_pts,.clock_id=0,
             .last={.system=1000000,.stream=old_pts}};
  ctx_t current={.rate=1,.coeff=1,.clock_id=1,
                 .wait_sync_ref={.system=1100000,.stream=new_pts}};
  vlc_clock_main_t owner={.context=&current,.wait_sync_ref_priority=0};
  vlc_list_init(&owner.prev_contexts);vlc_list_append(&old.node,&owner.prev_contexts);
  vlc_clock_t clock={.ops=&ops,.owner=&owner,.context=&old,.last_conversion=1000000};
  subpicture_t pics[2]={{.i_channel=3},{.i_channel=3}};
  spu_render_entry_t entries[2]={{.subpic=&pics[0],.orgstart=old_pts+10000,.orgstop=old_pts+50000},
   {.subpic=&pics[1],.orgstart=new_pts,.orgstop=new_pts+100000}};
  struct spu_channel channel={.clock=&clock,.rate=1,.entries={.data=entries,.size=2,.cap=2}};
  assert(spu_channel_UpdateDates(&channel,1100000)==2);
  if(entries[0].start!=1010000 || entries[0].stop!=1050000
     || entries[1].start!=1100000 || entries[1].stop!=1200000) {
   fprintf(stderr,"FAIL pending PCR timeline,backward=%d: old=%"PRId64"..%"PRId64" new=%"PRId64"..%"PRId64"\n",backward,entries[0].start,entries[0].stop,entries[1].start,entries[1].stop);return false;
  }
 }
 puts("PASS pending PCR timelines: real forward/backward jumps before master update");
 return true;
}

int main(void) {
 if(!pending_pcr_timelines()) return 4;
 if(!continuous_dialogue_gap()) return 3;
 if(!mixed_timeline_queue()) return 1;
 ctx_t old,current;vlc_clock_main_t main;vlc_clock_t clock;setup(&old,&current,&main,&clock);
 subpicture_t pics[2]={{.i_channel=3},{.i_channel=3}};
 spu_render_entry_t entries[2]={{.subpic=&pics[0],.orgstart=1404293002,.orgstop=1405207002},{.subpic=&pics[1],.orgstart=1405208002,.orgstop=1407000002}};
 struct spu_channel channel={.clock=&clock,.rate=1,.entries={.data=entries,.size=2,.cap=2}};
 bool queue_changed_reference=false;
 for(int frame=0;frame<20;frame++) {
  assert(spu_channel_UpdateDates(&channel,751678708555LL+frame*38960)==2);
  bool selected=spu_render_entry_IsSelected(&entries[0],3,751678746586LL+frame*42022,false);
  printf("frame=%d start=%lld stop=%lld selected=%d\n",frame,(long long)entries[0].start,(long long)entries[0].stop,selected);
  if(!selected) { fprintf(stderr,"FAIL cue522: selected subtitle becomes waiting within its914ms duration\n");return 1; }
  assert(entries[0].stop-entries[0].start==914000);
  assert(entries[1].stop-entries[1].start==1792000);
  vlc_tick_t reference=clock.last_conversion;
  subpicture_t future={.i_start=1408000002,.i_stop=1410000002};queue_dates(&channel,&future,751678708555LL+frame*38960);
  if(clock.last_conversion!=reference) queue_changed_reference=true;
  assert(future.i_stop-future.i_start==2000000);
 }
 if(queue_changed_reference) {fprintf(stderr,"FAIL future cue advances playback reference\n");return 1;}
 // A future cue can precede the active cue in the queue. Use the earliest
 // start, rather than relying on insertion order, to choose the timeline.
 setup(&old,&current,&main,&clock);
 spu_render_entry_t reversed[2]={entries[1],entries[0]};
 channel.entries.data=reversed;
 assert(spu_channel_UpdateDates(&channel,751678708555LL)==2);
 assert(spu_render_entry_IsSelected(&reversed[1],3,751678746586LL,false));
 assert(reversed[1].stop-reversed[1].start==914000);
 assert(clock.last_conversion==reversed[1].start);
 channel.entries.data=entries;
 // Delay, rate and scalar conversion keep their existing numerical contract.
 setup(&old,&current,&main,&clock);clock.context=&current;current.rate=2;clock.delay=250000;main.delay=50000;channel.rate=2;
 assert(spu_channel_UpdateDates(&channel,751678708555LL)==2);
 assert(entries[0].stop-entries[0].start==457000);
 uint32_t id;vlc_tick_t expected=vlc_clock_ConvertToSystem(&clock,751678708555LL,1404293002,2,&id);assert(entries[0].start==expected && id==1 && clock.last_conversion==expected);
 // Invalid stop/OSD/empty channels preserve their contracts.
 entries[0].orgstop=VLC_TICK_INVALID;assert(spu_channel_UpdateDates(&channel,751678708555LL)==2);assert(entries[0].stop==VLC_TICK_INVALID);
 channel.clock=NULL;entries[0].start=123;entries[0].stop=456;assert(spu_channel_UpdateDates(&channel,1)==2 && entries[0].start==123 && entries[0].stop==456);
 assert(spu_render_entry_IsSelected(&entries[0],3,123,false));pics[0].i_channel=1;assert(!spu_render_entry_IsSelected(&entries[0],1,123,true));channel.entries.size=0;assert(spu_channel_UpdateDates(&channel,1)==0);
 puts("PASS exact clock/SPU:20frames,cue durations,future queue,2x rate,delay,invalid stop,OSD,empty channel");
}
"""


def run(source, headers):
    clock = (source / "src/clock/clock.c").read_text()
    spu = (source / "src/video_output/vout_subpictures.c").read_text()
    parts = [
        function(clock, n)
        for n in [
            "context_stream_to_system",
            "vlc_clock_monotonic_to_system",
            "vlc_clock_slave_to_system",
            "context_get_closest",
            "vlc_clock_get_context",
            "vlc_clock_ConvertToSystem",
        ]
    ]
    for n in ["vlc_clock_GetConversionContext", "vlc_clock_ConvertToSystemWithContext"]:
        if re.search(r"\b" + n + r"\([^;]+?\)\s*\{", clock):
            parts.append(function(clock, n))
    parts += [
        function(spu, "spu_channel_UpdateDates"),
        function(spu, "spu_render_entry_IsSelected"),
    ]
    start = spu.index(
        "        vlc_clock_Lock(channel->clock);", spu.index("void spu_PutSubpicture(")
    )
    end = spu.index("        vlc_clock_Unlock(channel->clock);", start) + len(
        "        vlc_clock_Unlock(channel->clock);"
    )
    queue = (
        "static void queue_dates(struct spu_channel *channel,subpicture_t *subpic,vlc_tick_t system_now) { vlc_tick_t orgstart=subpic->i_start,orgstop=subpic->i_stop;"
        + spu[start:end]
        + "}\n"
    )
    with tempfile.TemporaryDirectory(prefix="subtitle-clock-regression-") as d:
        p = Path(d)
        (p / "probe.c").write_text(PRE + "\n".join(parts) + queue + CASES)
        subprocess.run(
            [
                "cc",
                "-std=gnu11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-fsanitize=address,undefined",
                "-I",
                str(headers / "include"),
                str(p / "probe.c"),
                "-o",
                str(p / "probe"),
            ],
            check=True,
        )
        return subprocess.run([str(p / "probe")]).returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--headers", type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.source, args.headers or args.source))
