# Repair title-only retrieval relevance

The tutor's top-k retrieval can omit a useful section when the question matches
the section heading but the section body does not repeat those words. The
problem is visible in the selected passages and in the source text sent to the
tutor model.

Make the relevant section available when its heading matches the question, even
when an unrelated section appears first and `k=1`. Keep body-text relevance and
the existing top-k, case-normalization, input-immutability, full-context,
history, and mode behavior intact.

The task is limited to the retrieval and tutor-context behavior in
`app/source.py` and `app/tutor.py`. A fake tutor response is supplied by the
offline checks; no model service or network access is needed.
