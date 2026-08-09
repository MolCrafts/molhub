import type { MolvisViewerElement } from "@molcrafts/molvis-stage";
import type { DetailedHTMLProps, HTMLAttributes, Ref } from "react";

declare module "react" {
  namespace JSX {
    interface IntrinsicElements {
      "molvis-viewer": DetailedHTMLProps<
        HTMLAttributes<MolvisViewerElement>,
        MolvisViewerElement
      > & {
        ref?: Ref<MolvisViewerElement>;
        src?: string;
        format?: string;
        controls?: string;
        modes?: string;
        mode?: string;
        representation?: string;
        background?: string;
        width?: string;
        height?: string;
      };
    }
  }
}
