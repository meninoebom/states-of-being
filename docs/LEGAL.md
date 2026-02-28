# Song Blender — Legal Landscape

Researched 2026-02-27. Not legal advice — notes for future decisions.

## Core Issue

Stem separation + loop chopping of copyrighted songs creates a **derivative work** under US copyright law (17 USC 106). The copyright holder has exclusive rights to prepare derivative works. This applies regardless of how automated or transformative the process is.

Every song has **two separate copyrights**: the composition (songwriters/publishers) and the sound recording (labels/artists). You need rights to both.

## Fair Use Assessment

Fair use is a defense, not a right. Four-factor analysis:

| Factor | Assessment |
|--------|-----------|
| **1. Purpose & character** | Partially favorable — biofeedback/movement control is genuinely transformative. But commercial use (premium tier) weighs against. |
| **2. Nature of work** | Unfavorable — music is highly creative, most protected category. |
| **3. Amount used** | Unfavorable — entire song is processed and stored, even if users hear fragments. |
| **4. Market effect** | Mixed — doesn't replace listening market, but could compete with official stem/remix products. |

**Overall: unlikely to succeed.** Music fair use cases are notoriously hard to win. The only major win (*Campbell v. Acuff-Rose*) involved parody.

## Legal Exposure

| Scale | Risk |
|-------|------|
| Small & free, < 1000 users | Low enforcement probability, but exposure exists |
| Growing or charging money | Statutory damages $750–$150,000 per song infringed |
| Curated library of 50 songs | Theoretical exposure up to $7.5M |

Practical consequences: DMCA takedowns, cease-and-desist, hosting termination, lawsuit.

## Relevant Precedents

- **Stem Player (Kanye)** — Licensed directly (Kanye owns his masters). Got takedowns when hosting other artists.
- **Moises.ai** — User-upload only, no hosted library. Operates in gray area under DMCA safe harbor. No major lawsuit yet.
- **Pacemaker (DJ app)** — Licensed catalog through label deals. Raised VC to fund licensing.
- **Bridgeport Music v. Dimension Films (2005)** — Any sampling of a sound recording requires a license (6th Circuit).
- **Capitol Records v. ReDigi (2018)** — Courts hostile to novel digital music use cases.

## Viable Strategies

### Pre-cleared library (safest for curated/free tier)
- CC-licensed music (ccMixter, Free Music Archive)
- Public domain (Musopen — classical recordings)
- Direct deals with indie artists who opt in
- AI-generated music (Suno, Udio — you typically own outputs, but legal landscape evolving)
- Splice sample packs (pre-cleared for music production, but loops not full songs)

### User-upload model (defensible for premium tier)
- Users upload their own files, platform processes them
- Register DMCA agent with Copyright Office
- Implement takedown/notice process
- ToS places rights responsibility on users
- Moises.ai precedent — this model has survived so far

### Direct artist partnerships
- The biofeedback angle is a genuine pitch: "Your song becomes an interactive movement experience"
- Independent artists may actively want to participate
- Start small, scale licensing as revenue grows

## Open Threads to Explore Later

- Some artists may have explicitly opened their catalogs for remix (e.g., possible FKA twigs statement? — unverified, worth researching)
- Creative Commons music that actually sounds good enough for the product
- Whether the "free tier only" angle meaningfully reduces risk (probably not legally, but practically reduces enforcement attention)
- Commissioning original music specifically for the platform
- Whether the experience is compelling enough that catalog recognition doesn't matter (hypothesis: yes — the interaction IS the product)

## DMCA Safe Harbor Checklist (for user-upload tier)

If/when we add user uploads:
- [ ] Register DMCA agent with US Copyright Office
- [ ] Publish DMCA policy on the site
- [ ] Implement takedown request process
- [ ] Implement counter-notification process
- [ ] Act expeditiously on valid takedown notices
- [ ] Do not have actual knowledge of specific infringement
- [ ] ToS requires users to have rights to uploaded content
