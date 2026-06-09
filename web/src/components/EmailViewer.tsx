import { useState } from "react";
import useSWR from "swr";
import { API, jsonFetcher as fetcher } from "../api";
import { formatEmailDateTime, splitOwnAndQuoted } from "../utils/email";

interface Email {
  email_id: string;
  from_addr: string;
  date: number; // unix ms
  subject?: string;
  to_addrs?: string[];
  cc_addrs?: string[];
  content?: string;
  thread_id?: string;
}

function QuotedBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(!open)}
        className="text-sol-base01 hover:text-sol-blue text-xs cursor-pointer"
      >
        {open ? "Hide quoted" : "Show quoted"}
      </button>
      {open && (
        <pre className="text-sol-base01 text-xs whitespace-pre-wrap break-words mt-1">{text}</pre>
      )}
    </div>
  );
}

interface EmailViewerProps {
  emailId: string | null;
}

export default function EmailViewer({ emailId }: EmailViewerProps) {
  const swrKey = emailId ? `${API}/api/email/${encodeURIComponent(emailId)}` : null;
  const { data: email, isLoading, error } = useSWR<Email>(swrKey, fetcher, { revalidateOnFocus: false });

  if (!emailId) {
    return (
      <div className="h-full flex items-center justify-center bg-sol-base03">
        <p className="text-sol-base01 italic text-sm">Select an email to read</p>
      </div>
    );
  }
  if (isLoading && !email) {
    return <div className="h-full bg-sol-base03"><p className="text-sol-base01 italic text-sm p-4">Loading...</p></div>;
  }
  if (error || !email) {
    return <div className="h-full bg-sol-base03"><p className="text-sol-red text-sm p-4">Failed to load email</p></div>;
  }

  const { own, quoted } = splitOwnAndQuoted(email.content);

  return (
    <div className="h-full overflow-y-auto bg-sol-base03 text-sm">
      <div className="max-w-3xl mx-auto px-4 py-4">
        <h1 className="text-sol-base1 text-lg font-medium mb-3 break-words">{email.subject || "(no subject)"}</h1>
        <div className="space-y-1 text-xs pb-3 mb-3 border-b border-sol-base02">
          <div><span className="text-sol-base01">From:</span> <span className="text-sol-base0">{email.from_addr}</span></div>
          {email.to_addrs && email.to_addrs.length > 0 && (
            <div><span className="text-sol-base01">To:</span> <span className="text-sol-base0">{email.to_addrs.join(", ")}</span></div>
          )}
          {email.cc_addrs && email.cc_addrs.length > 0 && (
            <div><span className="text-sol-base01">Cc:</span> <span className="text-sol-base0">{email.cc_addrs.join(", ")}</span></div>
          )}
          <div><span className="text-sol-base01">Date:</span> <span className="text-sol-base0">{formatEmailDateTime(email.date)}</span></div>
        </div>
        {email.content && (
          <div>
            <pre className="text-sol-base0 text-sm whitespace-pre-wrap break-words leading-relaxed">{own}</pre>
            <QuotedBlock text={quoted} />
          </div>
        )}
      </div>
    </div>
  );
}
