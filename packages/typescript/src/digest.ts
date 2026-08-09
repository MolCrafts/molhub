import { InvalidDigest } from "./errors.js";

const HEX_LENGTHS = new Map([
  ["md5", 32],
  ["sha1", 40],
  ["sha256", 64],
  ["sha512", 128],
]);

export class Digest {
  readonly algorithm: string;
  readonly hex: string;

  constructor(algorithm: string, hex: string) {
    const normalizedAlgorithm = algorithm.toLowerCase();
    const normalizedHex = hex.trim().toLowerCase();
    const length = HEX_LENGTHS.get(normalizedAlgorithm);
    if (length === undefined) throw new InvalidDigest(`Unsupported digest algorithm ${algorithm}.`);
    if (normalizedHex.length !== length || !/^[0-9a-f]+$/.test(normalizedHex)) {
      throw new InvalidDigest(
        `${normalizedAlgorithm} digest must be ${length} hexadecimal characters.`,
      );
    }
    this.algorithm = normalizedAlgorithm;
    this.hex = normalizedHex;
  }

  static parse(text: string): Digest {
    const separator = text.indexOf(":");
    if (separator <= 0) throw new InvalidDigest("Digest must use algorithm:hex format.");
    return new Digest(text.slice(0, separator), text.slice(separator + 1));
  }

  matches(other: Digest): boolean {
    return this.algorithm === other.algorithm && this.hex === other.hex;
  }

  toString(): string {
    return `${this.algorithm}:${this.hex}`;
  }
}

export async function digestBytes(bytes: BufferSource, algorithm = "sha256"): Promise<Digest> {
  const webAlgorithm = algorithm.toUpperCase().replace("SHA", "SHA-");
  const result = await crypto.subtle.digest(webAlgorithm, bytes);
  const hex = [...new Uint8Array(result)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return new Digest(algorithm, hex);
}
