/* Acceptance oracle: compile against the unchanged, pinned llama2.c run.c.
 * Usage: driver checkpoint.bin tok512.bin "prompt"
 * No sampling or independently reimplemented transformer lives in this driver.
 */
#define TESTING
#include "run.c"

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: %s checkpoint tokenizer prompt\n", argv[0]);
        return EXIT_FAILURE;
    }
    Transformer model = {0};
    Tokenizer tokenizer = {0};
    build_transformer(&model, argv[1]);
    build_tokenizer(&tokenizer, argv[2], model.config.vocab_size);
    /* UTF-8 byte fallback cannot produce more tokens than bytes, plus BOS
       and the dummy prefix. Do not size this buffer by the context window. */
    size_t capacity = strlen(argv[3]) + 3;
    int *tokens = calloc(capacity, sizeof(*tokens));
    if (!tokens) {
        fprintf(stderr, "cannot allocate prompt tokens\n");
        return EXIT_FAILURE;
    }
    int count = 0;
    encode(&tokenizer, argv[3], 1, 0, tokens, &count);
    if (count < 1 || count > model.config.seq_len) {
        fprintf(stderr, "prompt token count %d outside context window\n", count);
        return EXIT_FAILURE;
    }
    printf("{\"tokens\":[");
    for (int pos = 0; pos < count; pos++) {
        if (tokens[pos] < 0 || tokens[pos] >= model.config.vocab_size) {
            fprintf(stderr, "invalid token at position %d\n", pos);
            return EXIT_FAILURE;
        }
        printf("%s%d", pos ? "," : "", tokens[pos]);
    }
    printf("],\"logits\":[");
    for (int pos = 0; pos < count; pos++) {
        float *logits = forward(&model, tokens[pos], pos);
        printf("%s[", pos ? "," : "");
        for (int id = 0; id < model.config.vocab_size; id++) {
            if (!isfinite(logits[id])) {
                fprintf(stderr, "non-finite logit at position %d, id %d\n", pos, id);
                return EXIT_FAILURE;
            }
            printf("%s%.9g", id ? "," : "", (double)logits[id]);
        }
        printf("]");
    }
    printf("]}\n");
    free(tokens);
    free_tokenizer(&tokenizer);
    free_transformer(&model);
    return EXIT_SUCCESS;
}
