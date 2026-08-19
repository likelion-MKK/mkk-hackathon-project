export class AsyncFlowController {
  private generation = 0;
  private operationTail: Promise<void> = Promise.resolve();

  captureGeneration(): number {
    return this.generation;
  }

  invalidateCurrentFlow(): number {
    this.generation += 1;
    return this.generation;
  }

  isCurrent(generation: number): boolean {
    return generation === this.generation;
  }

  runSerialized<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.operationTail.then(operation, operation);

    this.operationTail = result.then(
      () => undefined,
      () => undefined,
    );

    return result;
  }
}
