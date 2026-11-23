# Ground-truth dataset format

Add manually verified institutional questions as JSON Lines. Do not include invented institutional answers or mark model output as ground truth. Keep the source document and reviewer traceable to an approved institutional copy.

Each line follows `question.schema.json`: a stable question ID, question text, optional language/as-of date, expected answer, relevant chunk IDs, expected abstention, and optional human annotations from a run. Store the dataset owner/reviewer and source corpus version in the accompanying dataset metadata file. The repository intentionally contains no sample placement policy or fabricated benchmark labels.
