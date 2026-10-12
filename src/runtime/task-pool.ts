/** FIFO task queue with least-active, round-robin tie-breaking resource leases.
 * A resource stays leased until the entire callback finishes, including failures.
 */
export class TaskPool<T> {
  private active: number[];
  private cursor = 0;
  private waiting: Array<() => void> = [];
  constructor(private resources: readonly T[], private capacity: number) {
    if (!resources.length || !Number.isInteger(capacity) || capacity < 1) {
      throw new Error("TaskPool needs resources and a positive capacity per resource");
    }
    this.active = resources.map(() => 0);
  }
  private pick(): number {
    let best = -1;
    for (let offset = 0; offset < this.resources.length; offset++) {
      const i = (this.cursor + offset) % this.resources.length;
      if (this.active[i]! < this.capacity
        && (best < 0 || this.active[i]! < this.active[best]!)) best = i;
    }
    return best;
  }
  async run<R>(work: (resource: T, index: number) => Promise<R>): Promise<R> {
    const index = await new Promise<number>((resolve) => {
      const acquire = () => {
        const i = this.pick();
        if (i < 0) { this.waiting.push(acquire); return; }
        this.active[i]!++;
        this.cursor = (i + 1) % this.resources.length;
        resolve(i);
      };
      acquire();
    });
    try { return await work(this.resources[index]!, index); }
    finally { this.active[index]!--; this.waiting.shift()?.(); }
  }
}
