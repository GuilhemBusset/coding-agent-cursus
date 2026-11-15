/** Minimal boundary smoke, not a completed research checkpoint or autonomy proof. */
export async function run(api: { model(): Promise<unknown>; tools(): Promise<unknown> }) {
  await api.model();
  await api.tools();
  await api.model();
}
