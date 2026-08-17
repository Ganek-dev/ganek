"use client";

import * as React from "react";

import * as SwitchPrimitive from "@radix-ui/react-switch";

/** Thin shadcn-style wrapper over Radix Switch, styled with house tokens.
Replaces the hand-rolled role="switch" buttons (job form, builder). */

const SIZES = {
  md: { track: "h-5 w-9", thumb: "h-4 w-4 data-[state=checked]:translate-x-4" },
  sm: { track: "h-[18px] w-8", thumb: "h-3.5 w-3.5 data-[state=checked]:translate-x-3.5" },
} as const;

function Switch({
  size = "md",
  className = "",
  ...props
}: { size?: keyof typeof SIZES } & React.ComponentPropsWithoutRef<
  typeof SwitchPrimitive.Root
>) {
  const sz = SIZES[size];
  return (
    <SwitchPrimitive.Root
      className={`relative shrink-0 rounded-full border transition-colors data-[state=checked]:border-transparent data-[state=checked]:bg-accent data-[state=unchecked]:border-edge data-[state=unchecked]:bg-muted-fill ${sz.track} ${className}`}
      {...props}
    >
      <SwitchPrimitive.Thumb
        className={`block translate-x-0.5 rounded-full bg-surface shadow-sm transition-transform ${sz.thumb}`}
      />
    </SwitchPrimitive.Root>
  );
}

export { Switch };
