# Independent aggregate calculation

Input: [`../config/compare-fixtures/aggregate.v1.json`](../config/compare-fixtures/aggregate.v1.json).
This small synthetic arithmetic fixture is separate from the announced comparison
schedules. It has two attempts per case so both failures and successes contribute
to the denominators. Its raw trace events and saved measurements describe the
following six attempts; the test checks trace accounting before aggregation.

| Attempt | Quality | Model input + output tokens | Model attempts / requests | Tools | Required facts |
| --- | --- | --- | --- | --- | --- |
| A1 | pass | 100 + 20 = 120 | 1 / 1 | 1 | 10 / 10 |
| A2 | fail | 180 + 20 = 200 | 1 / 1 | 2 | 8 / 10 |
| B1 | pass after retry | (20 + 10) failed + (100 + 20) retry = 150 | 2 / 1 | 1 | 10 / 10 |
| B2 | pass | 200 + 30 = 230 | 1 / 1 | 2 | 10 / 10 |
| C1 | fail | 100 + 50 = 150 | 1 / 1 | 1 | 6 / 10 |
| C2 | pass | 200 + 50 = 250 | 1 / 1 | 1 | 10 / 10 |

- Successes: 4 of 6 = 2/3. Per-case pass rates: A 1/2, B 2/2, C 1/2.
- Model attempts: 1 + 1 + 2 + 1 + 1 + 1 = 7, for 6 logical requests.
  Tool invocations: 1 + 2 + 1 + 2 + 1 + 1 = 8. One metered service error.
- Input: 100 + 180 + 20 + 100 + 200 + 100 + 200 = 900.
  Output: 20 + 20 + 10 + 20 + 30 + 50 + 50 = 200.
- **All-attempt total: 1,100 tokens. Tokens per success: 1,100 / 4 = 275.**
  The failed attempt, failed request and retry all remain in the numerator.
- Cache reads: 10 + 0 + (0 + 10) + 20 + 10 + 20 = 70; cache writes: 0.
  Reasoning: 2 + 2 + (1 + 2) + 3 + 5 + 5 = 20. Cache reads are already part
  of input, reasoning already part of output; neither is added to 1,100 again.
- Required facts: 10 + 8 + 10 + 10 + 6 + 10 = 54 / 60 = 90%.
  Citation and decisive checks each pass 4 / 6; failures identify A and C.
- All six stop reasons are completed (two completed answers fail quality).
  Elapsed milliseconds: 10 + 20 + 30 + 40 + 50 + 60 = 210, diagnostic only.

With zero quality successes, the efficiency denominator is zero: the result is
failure and `tokens_per_success: null`, never zero or a finite score. With unknown
input/output usage, only known field subtotals are available. If only cache detail
is missing, the observed token total stays available but efficiency conclusions
remain blocked until every usage field is complete.

The runnable scripted comparison is a different, class-schedule demonstration:
three attempts per version, every answer passing machine quality gates. Baseline
makes three 120-token calls per case; candidate makes two. Baseline: 9 calls,
1,080 tokens / 3 successes = **360 tokens/success**. Candidate: 6 calls,
720 tokens / 3 successes = **240 tokens/success**. Each version makes three tool
calls. This is a quality-preserving reduction; elapsed time is not ranked.
Both the scripted comparison and this arithmetic fixture remain synthetic, and
peer prose review remains pending.
