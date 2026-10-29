export const corpus = [
  [
    "backup",
    "Backups protect documents from accidental loss. To restore a deleted document, open the backup archive and recover the latest saved copy. Keep daily snapshots on a separate drive.",
  ],
  [
    "password",
    "Account security requires unique passwords and two factor authentication. A password manager generates strong credentials. Never share a verification code.",
  ],
  [
    "vector",
    "Vector search finds semantically related text using embedding similarity. Documents and queries are encoded by the same model. Cosine distance compares their meaning.",
  ],
  [
    "hybrid",
    "Hybrid search combines semantic vector retrieval with keyword full text search. seekdb fuses both result sets inside the database using reciprocal rank fusion.",
  ],
  [
    "gpu",
    "WebGPU accelerates machine learning in a modern browser using the local graphics processor. If WebGPU is unavailable, WebAssembly executes the same embedding model on the CPU.",
  ],
  [
    "quant",
    "INT8 quantization stores neural network weights as eight bit integers instead of thirty two bit floats. Smaller models download faster and consume less memory. Check retrieval quality after quantization.",
  ],
  [
    "batch",
    "Batch processing groups multiple documents in a single embedding call. Reusing a loaded model avoids initialization overhead on every query. Measure latency after warmup.",
  ],
  [
    "index",
    "Full text indexes may need a refresh after document insertion. Wait until newly imported documents become searchable before reporting completion. Batch writes reduce repeated refresh costs.",
  ],
  [
    "collection",
    "A collection separates one knowledge base from another. Store document identifiers, text, vectors and source metadata together. Switching collections should never return documents from a previous collection.",
  ],
  [
    "water",
    "Indoor plants need sunlight and moderate watering. Let the top soil dry before adding water. Excess moisture can damage roots.",
  ],
  [
    "train",
    "The train station opens at six in the morning. Passengers should arrive before departure and carry their tickets and identity documents.",
  ],
  [
    "bread",
    "To bake bread mix flour, water and yeast. Let the dough rise in a warm place, then bake until the crust turns golden.",
  ],
  [
    "cache",
    "Browser caching keeps downloaded model files on the device for later sessions. A cached load still needs model initialization. Report cold download time separately from warm inference latency.",
  ],
  [
    "privacy",
    "Local inference processes document contents on the user device. No cloud inference API is required. A local database stores the original text and computed embeddings.",
  ],
  [
    "chunk",
    "Long documents are split into overlapping text chunks. Preserve source filenames and chunk numbers so search results can display their original context.",
  ],
  [
    "quality",
    "Evaluate retrieval on a fixed corpus with labeled relevant documents. Recall at three measures whether relevant items appear among the first three results. Compare the same queries before and after quantization.",
  ],
];
export const queries = [
  ["How can I recover a removed file?", "backup"],
  ["How do I secure my login?", "password"],
  ["Find documents with similar meaning", "vector"],
  ["Combine keywords with semantic similarity", "hybrid"],
  ["What happens when graphics acceleration is unavailable?", "gpu"],
  ["How do eight bit weights reduce model size?", "quant"],
  ["Speed up encoding many documents together", "batch"],
  ["Why are newly inserted texts not searchable yet?", "index"],
  ["Keep different knowledge bases isolated", "collection"],
  ["When should I water a houseplant?", "water"],
  ["Where do passengers board the railway?", "train"],
  ["How to prepare dough for baking?", "bread"],
  ["Reuse downloaded weights across browser visits", "cache"],
  ["Can documents be processed without a cloud service?", "privacy"],
  ["Split a long file and preserve its source", "chunk"],
  ["How should retrieval accuracy be measured?", "quality"],
];
