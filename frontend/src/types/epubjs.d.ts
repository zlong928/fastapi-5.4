declare module "epubjs" {
  export interface Book {
    renderTo(
      element: HTMLElement | string,
      options: {
        width?: string | number;
        height?: string | number;
        flow?: string;
        spread?: string;
      }
    ): Rendition;
    destroy(): void;
  }

  export interface Rendition {
    display(target?: string): Promise<void>;
    next(): Promise<void>;
    prev(): Promise<void>;
    on(event: "relocated", callback: (location: { start?: { cfi?: string } }) => void): void;
    destroy(): void;
  }

  export default function ePub(
    url: string,
    options?: {
      openAs?: "epub" | "binary" | "base64" | "json" | "directory";
      requestHeaders?: Record<string, string>;
    }
  ): Book;
}
