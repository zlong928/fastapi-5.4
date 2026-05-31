import * as React from "react"
import { cn } from "@/lib/utils"

interface DropdownMenuProps {
  children: React.ReactNode
}

interface DropdownMenuTriggerProps {
  children: React.ReactNode
  asChild?: boolean
}

interface DropdownMenuContentProps {
  children: React.ReactNode
  align?: "start" | "center" | "end"
}

interface DropdownMenuItemProps {
  children: React.ReactNode
  onClick?: () => void
  disabled?: boolean
}

const DropdownMenuContext = React.createContext<{
  open: boolean
  setOpen: (open: boolean) => void
}>({
  open: false,
  setOpen: () => {},
})

export function DropdownMenu({ children }: DropdownMenuProps) {
  const [open, setOpen] = React.useState(false)

  return (
    <DropdownMenuContext.Provider value={{ open, setOpen }}>
      <div className="relative inline-block">{children}</div>
    </DropdownMenuContext.Provider>
  )
}

export function DropdownMenuTrigger({ children }: DropdownMenuTriggerProps) {
  const { open, setOpen } = React.useContext(DropdownMenuContext)

  return (
    <div onClick={() => setOpen(!open)}>
      {children}
    </div>
  )
}

export function DropdownMenuContent({ children, align = "end" }: DropdownMenuContentProps) {
  const { open, setOpen } = React.useContext(DropdownMenuContext)
  const ref = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    if (open) {
      document.addEventListener("mousedown", handleClickOutside)
      return () => document.removeEventListener("mousedown", handleClickOutside)
    }
  }, [open, setOpen])

  if (!open) return null

  return (
    <div
      ref={ref}
      className={cn(
        "absolute top-full mt-2 z-50 min-w-[8rem] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg",
        align === "end" && "right-0",
        align === "start" && "left-0",
        align === "center" && "left-1/2 -translate-x-1/2"
      )}
    >
      <div className="p-1">{children}</div>
    </div>
  )
}

export function DropdownMenuItem({ children, onClick, disabled }: DropdownMenuItemProps) {
  const { setOpen } = React.useContext(DropdownMenuContext)

  const handleClick = () => {
    if (!disabled && onClick) {
      onClick()
      setOpen(false)
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled}
      className={cn(
        "relative flex w-full cursor-pointer select-none items-center rounded-lg px-3 py-2 text-sm outline-none transition-colors",
        "hover:bg-slate-100 focus:bg-slate-100",
        disabled && "pointer-events-none opacity-50"
      )}
    >
      {children}
    </button>
  )
}

export function DropdownMenuSeparator() {
  return <div className="my-1 h-px bg-slate-100" />
}
