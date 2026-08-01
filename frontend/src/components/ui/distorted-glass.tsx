"use client";

import { useId } from "react";
import { cn } from "@/lib/utils";

type DistortedGlassProps = {
  className?: string;
  tone?: "light" | "dark";
};

/**
 * Lightweight section transition adapted from Cult UI's DistortedGlass.
 * A unique filter id keeps multiple instances from sharing SVG definitions.
 */
export function DistortedGlass({
  className,
  tone = "light",
}: DistortedGlassProps) {
  const filterId = `hy-distorted-glass-${useId().replaceAll(":", "")}`;

  return (
    <div
      className={cn(
        "pointer-events-none relative isolate h-16 w-full overflow-hidden",
        className,
      )}
      aria-hidden="true"
    >
      <div className="absolute inset-0 overflow-hidden border-y border-white/10">
        <div
          className={cn(
            "size-full opacity-80",
            tone === "dark"
              ? "bg-[repeating-radial-gradient(circle_at_50%_50%,transparent_0,rgba(132,255,220,0.14)_10px,rgba(255,255,255,0.42)_31px)]"
              : "bg-[repeating-radial-gradient(circle_at_50%_50%,transparent_0,rgba(15,118,110,0.10)_10px,rgba(255,255,255,0.82)_31px)]",
          )}
          style={{
            backgroundSize: "6px 6px",
            filter: `url(#${filterId})`,
          }}
        />
        <div
          className={cn(
            "absolute inset-0",
            tone === "dark"
              ? "bg-gradient-to-b from-white/10 via-transparent to-emerald-950/30"
              : "bg-gradient-to-b from-white/55 via-white/10 to-transparent",
          )}
        />
      </div>

      <svg
        width="0"
        height="0"
        className="absolute"
        focusable="false"
      >
        <defs>
          <filter
            id={filterId}
            x="-10%"
            y="-30%"
            width="120%"
            height="160%"
            colorInterpolationFilters="sRGB"
          >
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.12 0.12"
              numOctaves="1"
              seed="7"
              result="warp"
            />
            <feDisplacementMap
              in="SourceGraphic"
              in2="warp"
              scale="28"
              xChannelSelector="R"
              yChannelSelector="G"
            />
          </filter>
        </defs>
      </svg>
    </div>
  );
}
