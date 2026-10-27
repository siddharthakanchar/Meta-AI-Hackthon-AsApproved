# Demo video — shot list and script

**Target 2:45.** Check the official limit before recording and trim to fit.

**The structural decision:** open on the image, not the regulation. Eighteen
lines about FCA paragraph numbers before a judge sees the product is how you
lose someone in the first fifteen seconds. Show the APR leaving the frame, *then*
say why it matters.

Record 1080p / 30fps, mic on, system audio off, browser at 110–125%, bookmarks
and notifications hidden. Everything runs from cache — no live API call, so
nothing can stall mid-take.

---

## 0:00–0:20 · The moment, almost silent

**Visual:** Variant review screen, `northfield_card_v2__v0_apr_animates_offscreen`.
Master and delivered variant side by side. Let the variant play. The APR slides
out of frame about a second in. The visibility timeline under it fills red.

**Audio:** nothing for the first 6 seconds. Let it land.

> "That's an approved credit-card ad on the left. On the right is what Meta
> actually delivered. The representative APR is on screen for one second of
> fifteen — the trigger, 'zero percent for twelve months', stays for all of it."

**Why this order:** the red timeline bar is the single best image in the product.
A preview shows frame zero, which looks perfectly compliant. The gap between
that and what was served *is* the pitch.

---

## 0:20–0:40 · The stakes, in one breath

**Visual:** cut to the Meta terms line on screen, then back.

> "From the twentieth of November, Meta's terms put any and all risks from its
> AI edits on the advertiser — including features Meta switches on itself. For a
> UK lender that's not a design problem. The FCA requires the representative APR
> to be no less prominent than the trigger that forced it. Nobody told this
> advertiser anything changed."

Keep it to these three beats: the date, the liability transfer, the silence.
Citations go later.

---

## 0:40–1:10 · How it knows

**Visual:** flip through the three tabs — master vs variant, the SSIM heat map,
then regions with the Reels zone shaded.

> "AsApproved aligns every delivered variant back to the approved master, diffs
> it, finds the warning and the APR, and measures them. Seconds on screen. Size
> against the ad's own body copy. Contrast. Border. And whether the platform's
> own caption block is sitting on top of the warning — which the FCA's social
> media guidance calls out by name."

**Visual:** scroll the findings panel. Land on the R8 card. Point at `measured`
and `threshold`.

> "Twelve FCA-derived rules decide. Every finding carries the measured value,
> the threshold, the citation and the frame it came from. The model never
> decides anything — it writes the note, and a validator throws the note away if
> it contains a number that isn't in the evidence."

---

## 1:10–1:35 · Block, and the thing that follows

**Visual:** click **Block**. Blast radius table, then dry-run payloads, then the
Prove table, then the evidence record appended.

> "One click. The lineage graph finds every other live ad using this asset
> *and* enrolled in the same enhancement — sharing the asset isn't enough, an ad
> that opted out isn't at risk. Fix once, opt out three."

**Visual:** point at the Prove column, which reads *could not verify*.

> "And it refuses to lie to you. We have no Marketing API write access, so that
> opt-out is a labelled dry run and every Prove row says 'could not verify' —
> not 'proven'. A fix reported as landed that nobody watched land makes the
> whole evidence trail worthless."

**This beat matters more than it looks.** Most demos would hide the dry run.
Showing it is the credibility moment.

---

## 1:35–1:55 · Tamper

**Visual:** Evidence screen. Chain reads INTACT. Click **Tamper with one
record**. It flips to TAMPERED, naming record 1, line 2.

> "Every decision lands in a hash-chained log. Change one byte —" *click* "— and
> verification names the exact record that broke. It can't detect records
> deleted off the end; that needs an anchored head, and the README says so."

---

## 1:55–2:25 · The numbers, including the bad ones

**Visual:** Benchmark screen, per-rule table.

> "Forty-eight variants from twelve approved masters. Ground truth is computed
> from what the generator drew, never from what the detector found. Every rule
> we can measure is at a hundred percent recall. Precision on three of them sits
> at fifty to fifty-seven percent — the warning is found and judged correctly,
> but a neighbouring rule sometimes trips with it."

**Visual:** scroll to the variant-level table.

> "A plain pixel diff gets ninety-five percent at spotting that *something*
> changed. That's the easy question. It gets zero on every rule except one,
> because 'which rule broke, by how much, against which threshold' is the only
> thing that goes in a compliance record."

**Visual:** pause on the three "not evaluated" rows.

> "Three rules have no evidence here and say so rather than scoring themselves
> a pass."

---

## 2:25–2:45 · Close

**Visual:** back to the hero screen, APR sliding out.

> "No Meta model has run yet — the credits haven't arrived, so everything you've
> seen came from the fallback detector, and every screen says which. SAM 3.1,
> Spark and Voice Transcribe are wired and waiting.
>
> AsApproved. Turn on Advantage+ without betting your licence."

---

## Numbers to read from the screen, not from memory

Generated by `python scripts/publish_numbers.py` from `eval/results.json`. Run it
on the day before recording; `--check` fails if this table has drifted. Still read
the figures off the screen in the take — this table is for knowing in advance what
the screen will say.

<!-- publish_numbers:video start — generated, do not edit by hand -->

| | |
|---|---|
| Hero case | APR on screen ~1s of 15s |
| Blast radius | whatever the screen shows for that variant |
| Variant level | 100% precision / 100% recall / 100% F1, 0/23 false blocks |
| Per-rule recall | 100% on 8 of 9 measured rules — except R12 80% |
| Weakest precision | R5 50%, R7 67% |
| Pixel-diff baseline | 95% F1 at variant level, 0% recall on every rule but R1 |
| Not evaluated | R9 (2 variants), R10 (2 variants), plus R2 which has no pixel expression |
| Speed | 3.3s per variant, against 0.4s for the pixel diff |

<!-- publish_numbers:video end -->

## Hard rules for the take

- **Do not say "SAM 3.1 tracks the APR"** while the fallback is what ran. Say
  what ran. If credits arrive before recording, re-record this line rather than
  fudging it.
- **Do not present 100% as accuracy.** It is 100% on the 48 variants the
  thresholds were fitted on, with no held-out split. Say "on our development
  set" out loud, and name R12's false negative rather than waiting to be asked.
- **Do not call the dry run a fix.**
- Say "flags for compliance review" — never "ensures compliance".
- Nothing on screen may show an employer, a client, or a real brand.

## If credits arrive before recording

Add 15 seconds after the 1:10 mark:

<!-- publish_numbers:sam_video start — generated, do not edit by hand -->

Say this, and nothing stronger:

> "On the 4 variants we get wrong, our keyless tracker finds the warning 1 time in 4 — mean region IoU 0.25. SAM 3.1 finds it 4 times out of 4, mean IoU 0.99. That is the gap the model closes."

Do not claim the rule outcomes change — they do not. This measures
localisation, which is what the errors were. If asked why SAM is not wired
into the benchmark: because swapping it in would change every published
number, and there was no time to re-verify the reproducibility result before
the deadline.

<!-- publish_numbers:sam_video end -->

That is the strongest possible use of the model: a measured delta against a real
classical control, not a swap-in nobody can evaluate. The metric was promised in
the README before the numbers existed, so it reads as a kept promise rather than
a patch.
