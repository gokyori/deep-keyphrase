# -*- coding: UTF-8 -*-
import torch


class BeamSearch(object):
    def __init__(self, model, beam_size, max_target_len, id2vocab, bos_idx):
        self.model = model
        self.beam_size = beam_size
        self.id2vocab = id2vocab
        self.max_target_len = max_target_len
        self.bos_idx = bos_idx

    def generate(self, src_tokens, src_lens, src_tokens_with_oov, oov_counts, oov_list):
        batch_size = len(src_tokens)
        encoder_output_dict = None
        hidden_state = None
        prev_output_tokens = [[self.bos_idx]] * batch_size
        decoder_state = torch.zeros(batch_size, self.model.decoder.target_hidden_size)

        model_output = self.model(src_tokens,
                                  src_lens,
                                  prev_output_tokens,
                                  encoder_output_dict,
                                  src_tokens_with_oov,
                                  oov_counts,
                                  decoder_state,
                                  hidden_state)
        decoder_prob, encoder_output_dict, decoder_state, hidden_state = model_output
        prev_best_probs, prev_best_index = torch.topk(decoder_prob, self.beam_size, 1)
        prev_decoder_state = decoder_state.repeat(self.beam_size, 1)
        prev_hidden_state = [hidden_state[0].repeat(1, self.beam_size, 1),
                             hidden_state[1].repeat(1, self.beam_size, 1)]
        result_sequences = prev_best_index.unsqueeze(2)
        encoder_output_dict = self.expand_encoder_output(encoder_output_dict)
        beam_batch_size = self.beam_size * batch_size
        for target_idx in range(self.max_target_len):
            model_output = self.model(src_tokens.repeat(self.beam_size, 1),
                                      src_lens.repeat(self.beam_size, 1),
                                      prev_best_index.view(-1, 1),
                                      encoder_output_dict,
                                      src_tokens_with_oov.repeat(self.beam_size, 1),
                                      oov_counts.repeat(self.beam_size),
                                      prev_decoder_state,
                                      prev_hidden_state
                                      )
            decoder_prob, encoder_output_dict, decoder_state, hidden_state = model_output
            decoder_prob = decoder_prob.view(batch_size, self.beam_size, -1)
            # decoder_state = decoder_state.view(batch_size, self.beam_size, -1)
            # hidden_state = decoder_state.view(batch_size, self.beam_size, -1)
            top_token_probs, top_token_index = torch.topk(decoder_prob, self.beam_size, 2)
            top_token_probs = top_token_probs.view(batch_size, -1)
            top_token_index = top_token_index.view(batch_size, -1)
            beam_best_probs, beam_best_index = torch.topk(top_token_probs, self.beam_size, 1)

            # B x b
            select_idx_factor = torch.tensor(range(batch_size)) * self.beam_size
            select_idx_factor = select_idx_factor.unsqueeze(1).repeat(1, self.beam_size)
            state_select_idx = beam_best_index.flatten() // self.beam_size + select_idx_factor.flatten()
            prev_best_index = torch.gather(top_token_index, 1, beam_best_index)
            prev_decoder_state = decoder_state.index_select(0, state_select_idx)

            prev_hidden_state[0] = hidden_state[0].index_select(1, state_select_idx)
            prev_hidden_state[1] = hidden_state[1].index_select(1, state_select_idx)
            result_sequences = torch.cat([result_sequences, prev_best_index.unsqueeze(2)], dim=2)
            prev_best_index = prev_best_index.view(beam_batch_size, -1)
        result_sequences = result_sequences.numpy().tolist()
        results = []
        for batch in result_sequences:
            beam_list = []
            for beam in batch:
                phrase = []
                for idx in beam:
                    if idx in self.id2vocab:
                        phrase.append(self.id2vocab[idx])
                    else:
                        phrase.append(oov_list[idx - len(self.id2vocab)])
                beam_list.append(''.join(phrase))
            results.append(beam_list)
        return results

    def expand_encoder_output(self, encoder_output_dict):
        encoder_output = encoder_output_dict['encoder_output']
        encoder_mask = encoder_output_dict['encoder_padding_mask']
        encoder_hidden_state = encoder_output_dict['encoder_hidden']
        output_size = [1] * len(encoder_output.size())
        output_size[0] *= self.beam_size
        mask_size = [1] * len(encoder_mask.size())
        mask_size[0] *= self.beam_size
        hidden_state1_size = [1] * len(encoder_hidden_state[0].size())
        hidden_state2_size = [1] * len(encoder_hidden_state[1].size())
        hidden_state1_size[1] *= self.beam_size
        hidden_state2_size[1] *= self.beam_size
        encoder_output = encoder_output.repeat(*output_size)
        encoder_mask = encoder_mask.repeat(*mask_size)
        encoder_hidden_state[0] = encoder_hidden_state[0].repeat(*hidden_state1_size)
        encoder_hidden_state[1] = encoder_hidden_state[1].repeat(*hidden_state2_size)
        encoder_output_dict['encoder_output'] = encoder_output
        encoder_output_dict['encoder_padding_mask'] = encoder_mask
        encoder_output_dict['encoder_hidden'] = encoder_hidden_state
        return encoder_output_dict
