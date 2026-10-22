import { forward } from "@/lib/proxy";
export const dynamic = "force-dynamic";
export async function POST(request: Request) {
  return forward(request, "/api/v1/replenishment/export");
}
