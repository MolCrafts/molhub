import { z } from "zod";

const exactVersion = z
  .string()
  .min(1)
  .refine((value) => value.toLowerCase() !== "latest", "Versions must be immutable");

export const derivedInspectionDescriptorSchema = z.object({
  schema_version: z.literal(1),
  source: z.object({
    coordinate: z.string().regex(/^(dataset|model|plugin):[^/]+\/[^@]+@[^@]+$/),
    role: z.string().min(1),
    digest: z.string().regex(/^[a-z0-9][a-z0-9._+-]*:[A-Fa-f0-9]+$/),
    size: z.number().int().nonnegative(),
  }),
  converter: z.object({
    name: z.string().min(1),
    version: exactVersion,
    commit: z.string().regex(/^[A-Fa-f0-9]{7,64}$/),
  }),
  molrec_schema_version: exactVersion,
  generated_at: z.iso.datetime(),
  record: z.object({
    format: z.literal("molrec-zarr-v3"),
    url: z.url().refine((value) => value.startsWith("https://"), "Record URL must use HTTPS"),
    frames: z.number().int().positive(),
  }),
  properties: z.array(
    z.object({
      name: z.string().min(1),
      target: z.enum(["structure", "atom", "environment"]),
      unit: z.string().min(1).optional(),
    }),
  ),
});

export type DerivedInspectionDescriptor = z.infer<typeof derivedInspectionDescriptorSchema>;

/** Stable input identity; output URL and generation time are intentionally excluded. */
export async function derivedInspectionKey(
  descriptor: DerivedInspectionDescriptor,
): Promise<string> {
  const valid = derivedInspectionDescriptorSchema.parse(descriptor);
  const identity = JSON.stringify({
    schema_version: valid.schema_version,
    source: valid.source,
    converter: valid.converter,
    molrec_schema_version: valid.molrec_schema_version,
    record_format: valid.record.format,
  });
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(identity));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}
