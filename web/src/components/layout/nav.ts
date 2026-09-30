import { Bell, Cpu, FileSearch, LayoutDashboard, MessageSquare, ScrollText, Settings, Upload } from "lucide-react";
import { can } from "@/lib/auth";

export const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, perm: null },
  { to: "/assistant", label: "Assistant", icon: MessageSquare, perm: null },
  { to: "/evidence", label: "Evidence", icon: FileSearch, perm: "evidence:read" },
  { to: "/uploads", label: "Uploads", icon: Upload, perm: "upload:inspect" },
  { to: "/alerts", label: "Alerts", icon: Bell, perm: "alerts:read" },
  { to: "/audit", label: "Audit log", icon: ScrollText, perm: "audit:read" },
  { to: "/devices", label: "Devices", icon: Cpu, perm: "device:register|evidence:read" },
  { to: "/settings", label: "Settings", icon: Settings, perm: null },
] as const;

export const allowed = (role: Parameters<typeof can>[0], perm: string | null) => !perm || perm.split("|").some((p) => can(role, p));

