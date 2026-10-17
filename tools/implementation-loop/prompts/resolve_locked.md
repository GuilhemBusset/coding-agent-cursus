Main moved on, and merging it into this branch conflicts in locked tests that the builder may not
touch: {{files}}. The merge is in progress in your working directory.

Resolve the conflict markers in those files only, keeping the requirements of both sides (main's
side tests work already merged; this branch's side tests this issue). Change nothing else. Do not
run `git merge`, `git commit` or `git merge --abort`: the engine concludes the merge.

{{feedback}}

Return the files you resolved and a short note.
