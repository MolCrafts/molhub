export class BoundedJsonReader {
  constructor(private readonly maximumBytes: number) {
    if (!Number.isSafeInteger(maximumBytes) || maximumBytes < 1) {
      throw new RangeError("maximumBytes must be a positive safe integer.");
    }
  }

  async read(response: Response): Promise<unknown> {
    const declared = Number(response.headers.get("content-length") ?? 0);
    if (Number.isFinite(declared) && declared > this.maximumBytes) {
      throw new Error(`JSON response exceeds ${this.maximumBytes} bytes.`);
    }
    if (!response.body) throw new Error("JSON response has no body.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let total = 0;
    let text = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > this.maximumBytes) {
        await reader.cancel();
        throw new Error(`JSON response exceeds ${this.maximumBytes} bytes.`);
      }
      text += decoder.decode(value, { stream: true });
    }
    try {
      return JSON.parse(text + decoder.decode());
    } catch (error) {
      throw new Error("Response body is not valid JSON.", { cause: error });
    }
  }
}
