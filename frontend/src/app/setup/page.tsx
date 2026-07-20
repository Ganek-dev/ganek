"use client";

import { useRouter } from "next/navigation";

import { AuthForm } from "@/components/AuthForm";
import { api } from "@/lib/api";

export default function SetupPage() {
  const router = useRouter();
  return (
    <AuthForm
      title="Set up your company"
      submitLabel="Create company"
      fields={[
        { name: "company_name", label: "Company name", type: "text" },
        { name: "email", label: "Admin email", type: "email" },
        { name: "password", label: "Password (min 10 chars)", type: "password", minLength: 10 },
      ]}
      onSubmit={async (values) => {
        await api.register({
          company_name: values.company_name,
          email: values.email,
          password: values.password,
        });
        router.push("/admin");
      }}
    />
  );
}
