"use client";

import { useRouter } from "next/navigation";

import { AuthForm } from "@/components/AuthForm";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  return (
    <AuthForm
      title="Sign in to Vetd"
      submitLabel="Sign in"
      fields={[
        { name: "email", label: "Email", type: "email" },
        { name: "password", label: "Password", type: "password" },
      ]}
      onSubmit={async (values) => {
        await api.login({ email: values.email, password: values.password });
        router.push("/admin");
      }}
    />
  );
}
