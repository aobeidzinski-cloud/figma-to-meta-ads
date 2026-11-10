You are writing the text assets for one Meta ad. The image is already made and approved; your job is the words around it.

Attached: the approved 4:5 image for the set "[SET_NAME]". Also provided: the brand voice notes below and, if available, the body and headline of the account's best-performing ad as a style reference.

Brand voice notes:
[BRAND_NOTES]

Style reference (optional):
[REFERENCE_AD]

Write JSON with exactly these fields and nothing else:

```json
{"bodies": ["...", "...", "...", "...", "..."],
 "titles": ["...", "...", "...", "...", "..."],
 "description": "..."}
```

Rules:
- Exactly 5 bodies (primary text). Each is 1 to 3 sentences, under 220 characters, and leads with a different angle: the specific pain the image shows, the concrete proof, the offer, the objection, the identity of the buyer. Meta tests all five against each other, so make them genuinely different, not rewordings.
- Exactly 5 titles (headlines). Under 40 characters each so they do not truncate in feed. No ending punctuation. No ALL CAPS.
- Exactly 1 description. Under 30 characters. A fact (shipping, price, timing), not a slogan.
- Every line must be true of what is on the image. Do not promise something the image does not show.
- Match the voice notes. If the notes and the reference ad disagree, follow the notes.
- No emojis, no hashtags, no "Click here". The CTA button handles the ask.
- Plain language a customer would say out loud. If a line sounds like an ad, rewrite it.

Save the result to `copy/[SET_NAME].json`. The build step reads that exact path.
