export default {
  async fetch(request) {
    const url = new URL(request.url);
    const fileId = url.searchParams.get("id");

    if (!fileId) {
      return new Response("Missing id parameter", { status: 400 });
    }

    // First request to get confirmation token
    const firstUrl = `https://drive.google.com/uc?export=download&id=${fileId}`;
    const firstResp = await fetch(firstUrl, {
      headers: { "User-Agent": "Mozilla/5.0" },
      redirect: "follow",
    });

    const html = await firstResp.text();

    // Extract confirm token if present
    const match = html.match(/confirm=([0-9A-Za-z_]+)/);
    const confirm = match ? match[1] : "t";

    // Second request with confirm token
    const finalUrl = `https://drive.google.com/uc?export=download&id=${fileId}&confirm=${confirm}`;
    const finalResp = await fetch(finalUrl, {
      headers: { "User-Agent": "Mozilla/5.0" },
      redirect: "follow",
    });

    return new Response(finalResp.body, {
      headers: {
        "Content-Type": "video/mp4",
        "Access-Control-Allow-Origin": "*",
      },
    });
  },
};