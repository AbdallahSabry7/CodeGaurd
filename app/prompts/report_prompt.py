REPORT_PROMPT = (
	"You are writing the final summary of an automated refactoring run. "
	"Use ONLY the facts in the JSON below — do not invent or infer results. "
	"Write 2-4 plain sentences covering: what was achieved, whether the code still "
	"runs, whether behavior was preserved, and what problems (if any) remain."
	"\n\nFACTS:\n{facts}"
)