"use client";

import * as React from "react";

import * as MenuPrimitive from "@radix-ui/react-dropdown-menu";
import { MoreHorizontal } from "lucide-react";

/** Thin shadcn-style wrapper over Radix DropdownMenu, styled with house
tokens. Replaces the hand-rolled ⋯ menus (jobs / team / applicant panel) and
brings keyboard navigation, focus management and outside-click dismissal
along for free. */

const Menu = MenuPrimitive.Root;
const MenuTrigger = MenuPrimitive.Trigger;

/** The standard ⋯ trigger. Pass `label` for the accessible name. */
function MenuDotsTrigger({
  label,
  className = "",
  ...props
}: { label: string } & React.ComponentPropsWithoutRef<typeof MenuPrimitive.Trigger>) {
  return (
    <MenuPrimitive.Trigger
      aria-label={label}
      className={
        className ||
        "inline-flex h-[30px] w-[30px] items-center justify-center rounded-sm text-g500 hover:bg-muted-fill data-[state=open]:bg-muted-fill"
      }
      {...props}
    >
      <MoreHorizontal aria-hidden className="h-4 w-4" />
    </MenuPrimitive.Trigger>
  );
}

function MenuContent({
  className = "",
  ...props
}: React.ComponentPropsWithoutRef<typeof MenuPrimitive.Content>) {
  return (
    <MenuPrimitive.Portal>
      <MenuPrimitive.Content
        align="end"
        sideOffset={4}
        className={`z-10 w-40 rounded-md border border-edge bg-surface py-1 text-left shadow-lg ${className}`}
        {...props}
      />
    </MenuPrimitive.Portal>
  );
}

function MenuItem({
  className = "",
  ...props
}: React.ComponentPropsWithoutRef<typeof MenuPrimitive.Item>) {
  return (
    <MenuPrimitive.Item
      className={`block w-full cursor-default px-3 py-1.5 text-left text-[13px] outline-none data-[highlighted]:bg-muted-fill ${className}`}
      {...props}
    />
  );
}

export { Menu, MenuTrigger, MenuDotsTrigger, MenuContent, MenuItem };
