# Architecture

```mermaid
flowchart TB
    subgraph approve["1 · Approve"]
        M[Approved master] --> MF[["SHA-256 + approver + timestamp<br/>+ rulebook version + enhancement settings"]]
        MF --> SIG[["Ed25519 signature<br/>(manifest.py)"]]
    end

    subgraph sense["2 · Sense"]
        API[("Meta Marketing API")] -->|enhancement settings| DRIFT[Settings drift → R2]
        API -->|ad previews| VAR[Delivered variant]
    end

    subgraph measure["3 · Measure — deterministic, no model decides"]
        VAR --> ALIGN["Align<br/>ORB + RANSAC homography"]
        ALIGN -->|ok?| GATE{{"geometry trusted?"}}
        GATE -->|no| INC1["R1/R3 → inconclusive"]
        GATE -->|yes| DIFF["Diff<br/>SSIM map → changed regions"]

        ALIGN --> LOC["Locate regions"]
        SAM[("SAM 3.1<br/>masks + video tracks")] -.->|when a key exists| LOC
        NCC["template + NCC<br/>(keyless fallback)"] --> LOC

        LOC --> MEAS["Measure<br/>seconds on screen · size · WCAG contrast<br/>border · clipping · occlusion"]
        OVL["Placement safe zones<br/>Feed / Stories / Reels"] --> MEAS
        OCR[("OCR")] --> TXT["Text + heights"]
        SPARK[("Muse Spark 1.3<br/>claim extraction, strict JSON")] -.-> TXT
        VOICE[("Muse Voice Transcribe<br/>turn-level")] --> AUD["Trigger spoken?<br/>APR spoken? → R9"]
    end

    subgraph decide["4 · Decide — rules only"]
        MEAS --> RULES["Rulebook uk_v1 · YAML<br/>R1–R12 + B1"]
        TXT --> RULES
        AUD --> RULES
        DIFF --> RULES
        DRIFT --> RULES
        SIG --> RULES
        RULES --> FIND["Findings<br/>fail · pass · inconclusive · n/a"]
    end

    subgraph explain["5 · Explain — model, then guard"]
        FIND --> NOTE["Muse Spark writes a note"]
        NOTE --> VALID{{"Validator:<br/>every number, rule ID,<br/>quote and citation<br/>present in evidence?"}}
        VALID -->|no| RETRY["retry once"] --> TPL["deterministic template"]
        VALID -->|yes| OUT["Compliance note"]
    end

    subgraph act["6 · Act and prove"]
        FIND --> HUMAN{{"Human decision<br/>Block / Accept / Escalate"}}
        HUMAN -->|Block| BLAST["Blast radius<br/>asset ∩ feature ∩ OPT_IN"]
        BLAST --> OPTOUT["Opt out N siblings<br/>(dry run without write access)"]
        OPTOUT --> PROVE{{"Prove:<br/>settings read back OPT_OUT<br/>AND preview matches master"}}
        PROVE -->|both| CLOSED["Closed – proven"]
        PROVE -->|either missing| OPEN["Open – not confirmed"]
    end

    subgraph prove["7 · Remember"]
        HUMAN --> LOG[("Hash-chained evidence log<br/>digest covers index + prev")]
        HUMAN --> PREC[("Precedent memory<br/>feature × asset × rule × outcome")]
    end

    OUT --> HUMAN
    CLOSED --> LOG

    classDef meta fill:#1877f2,stroke:#0b5ed7,color:#fff
    classDef guard fill:#e5484d,stroke:#b4353a,color:#fff
    classDef det fill:#30a46c,stroke:#217a4f,color:#fff
    class SAM,SPARK,VOICE,API meta
    class VALID,GATE,PROVE guard
    class RULES,MEAS,DIFF,ALIGN det
```

## The three load-bearing ideas

**Rules decide; the model explains.** Every verdict comes from a YAML rulebook
evaluated by deterministic code. Muse Spark extracts claims into a constrained
schema and writes prose — it never changes an outcome. The red boxes above are
guards, and each one can only make the system say *less*.

**"Could not measure" is a third outcome.** Every rule input may be `None`.
A rule with an unknown input returns `inconclusive`, never `pass` (which would
wave through a real breach) and never `fail` (which would accuse an advertiser
on a guess). There is a test asserting that an empty context produces zero
failures across all twelve rules.

**The baseline must be clean.** The approved masters are generated to satisfy
the rulebook — warning outside the placement's UI zone, own border, bold,
underlined, contrast ≥ 4.5:1, APR no less prominent than its trigger — and
tested for it. Measuring variants against a baseline that itself breached a rule
would make that rule's numbers meaningless. Building that test caught three real
breaches in our own masters.

## Where the Meta models sit

| Model | Job | Status without a key |
|---|---|---|
| **SAM 3.1** | Masks and video-tracks the warning box, APR, trigger, logo — frame by frame, stable IDs | Falls back to aligned template + normalised cross-correlation, **labelled as such in the UI** |
| **Muse Spark 1.3** | Claim and trigger extraction (strict JSON Schema); writes the compliance note | Falls back to OCR for text and a deterministic template for the note |
| **Muse Voice Transcribe** | Was the trigger spoken? Was the APR spoken? (R9) | No fallback exists — R9 reports `inconclusive` and those variants are **not evaluated**, never counted as passes |
| **Meta Marketing API** | Enhancement settings, previews, the opt-out write | R2 reports `inconclusive`; Act runs as a labelled dry run |

Every fallback is visible in the UI's provenance line. The point of the
region-IoU metric in the benchmark is to measure what SAM adds over the
fallback — a comparison that only means something because the fallback is a
real detector rather than a mock.
