import { Card } from "../ui/components";
export default function Placeholder({ title }: { title: string }) {
  return (
    <>
      <h1>{title}</h1>
      <Card as="div" className="empty">This module is coming in a later milestone.</Card>
    </>
  );
}
