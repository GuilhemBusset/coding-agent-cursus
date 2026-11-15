/** Completed bounded recovery: one retry, permanent errors retained, no invented answer.
 * The same example executes the public synthetic read scenarios.
 */
export async function recoverRead(api: any) {
  await api.model();
  const results = await api.tools();
  if (results.some((r: any) => r.status === 'error' && r.error.retryable)) {
    await api.model();
    return api.tools();
  }
  return results;
}
