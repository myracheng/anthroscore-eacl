"""
This script computes AnthroScore for a set of entities in a set of texts. It 
results in an output file with all parsed sentences from the texts and their 
corresponding AnthroScores.

EXAMPLE USAGE: 
To obtain AnthroScores for the terms "model" and "system" in 
abstracts from examples/acl_50.csv (a subset of ACL Anthology papers)

    python get_anthroscore.py --input_file example/acl_50.csv \
        --text_column_name abstract --entities system model \
        --output_file example/results.csv --text_id_name acl_id

You can also list the entities in a separate .txt file, 
specified by the argument --entity_filename

    python get_anthroscore.py --input_file example/acl_50.csv \
            --text_column_name abstract --entity_filename example/entities.txt \
            --output_file example/results.csv --text_id_name acl_id

"""

import re
import pandas as pd
import argparse
import spacy
nlp = spacy.load("en_core_web_sm")
import pandas as pd
import torch
from transformers import RobertaTokenizer, RobertaForMaskedLM
import numpy as np
import scipy
import gc
model = RobertaForMaskedLM.from_pretrained('roberta-base')
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model.to(device)
print("BERT model loaded on %s"%device)
tokenizer = RobertaTokenizer.from_pretrained('roberta-base')

def get_prediction(sent):
    terms = ['you', 'we', 'us', 'he', 'she', 'her', 'him', 'You', 'We', 'Us', 'He', 'She', 'Her', 'I','i', 'it', 'its', 'It', 'Its' ]
    target_inds = [tokenizer.get_vocab()[x] for x in terms]
    token_ids = tokenizer.encode(sent,return_tensors='pt').to(device)
    masked_position = (token_ids.squeeze() == tokenizer.mask_token_id).nonzero()
    try:
        masked_pos = [mask.item() for mask in masked_position][0]
    except IndexError:
        temp = tokenizer.encode(sent, return_tensors='pt').to(device)
        masked_position = (temp.squeeze() == tokenizer.mask_token_id).nonzero()
        try:
            if (int(masked_position[0] + 256)) > len(temp[0]):
                token_ids = torch.reshape(temp[0][-512:], (1, 512))
            else: 
                token_ids = torch.reshape(temp[0][masked_position[0] - 256:masked_position[0]+256], (1, 512))
        except IndexError:
            return np.empty((len(terms),))
        masked_position = (token_ids.squeeze() == tokenizer.mask_token_id).nonzero()
        masked_pos = [mask.item() for mask in masked_position ][0]
    
    with torch.no_grad():
        output = model(token_ids)

    last_hidden_state = output[0].squeeze()
    mask_hidden_state = last_hidden_state[masked_pos].cpu().numpy()

    probs = scipy.special.softmax(mask_hidden_state)
    scores = np.array([probs[i] for i in target_inds])
    return scores

def get_anthroscore(sentence_filename):
    terms = ['you', 'we', 'us', 'he', 'she', 'her', 'him', 'You', 'We', 'Us', 'He', 'She', 'Her', 'I','i', 'it', 'its', 'It', 'Its' ]
    df = pd.read_csv(sentence_filename)
    final =np.empty((len(terms),))
    for i,x in enumerate(df.masked_sentence):
        if i>0 and i%100 == 0:
            torch.cuda.empty_cache()
            gc.collect()
            print("Calculating sentence %d"%i)
        newrow = get_prediction(x)
        final = np.vstack([final, newrow])
    return final

def parse_sentences_from_file(input_filename, entities, text_column_name, id_column_name, output_filename):
    column_names = ['sentence','masked_sentence','text_id','POS','verb','original_term','original_noun']
    pattern_list = ['\\b%s\\b'%s for s in entities] # add boundaries

    df = pd.read_csv(input_filename).dropna(subset=text_column_name)
    final = []
    for i, k in df.iterrows():
        text = k[text_column_name]
        if len(id_column_name)>0:
            text_id = k[id_column_name]
        else:
            text_id = input_filename
        if text.strip():
            doc = nlp(text)
            for _parsed_sentence in doc.sents:
                for _noun_chunk in _parsed_sentence.noun_chunks:
                    if _noun_chunk.root.dep_ == 'nsubj' or _noun_chunk.root.dep_ == 'dobj':
                        for _pattern in pattern_list:
                            if re.findall(_pattern, _noun_chunk.text.lower()):
                                    _verb = _noun_chunk.root.head.lemma_.lower()
                                    target = str(_parsed_sentence).replace(str(_noun_chunk),'<mask>')
                                    final.append((str(_parsed_sentence), target, text_id, _noun_chunk.root.dep,str(_verb),_pattern.strip('\\b'),_noun_chunk.text.lower()))
    res = pd.DataFrame(final)
    res.columns =column_names
    res.to_csv(output_filename,index=False)
    print('%d sentences containing target entities found'%len(res))

def main():
    parser = argparse.ArgumentParser(description="Script to compute AnthroScore for a given set of texts",
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--input_file", help="Input CSV file of text(s) to compute AnthroScore on")
    parser.add_argument("--text_column_name", help="Column of input CSV containing text(s) to compute AnthroScore on.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--entities",nargs="+", type=str,help="Entities to compute AnthroScore for")
    group.add_argument('--entity_filename',default='',help=".txt file of entities to compute AnthroScore for")
    parser.add_argument("--output_file", default='',help="Location to store output of parsed sentences with AnthroScores, optional")
    parser.add_argument("--text_id_name",type=str,default='',help="ID metadata to save for every sentence parsed, optional")
    
        
    args = parser.parse_args()

    input_file = args.input_file
    output_file = args.output_file
    if output_file is None:
        output_file = '%s_parsed.csv'%(input_file.split('.')[0])
    assert input_file[-4:]=='.csv'
    assert output_file[-4:]=='.csv'
        
    text_column_name = args.text_column_name
    if len(args.entity_filename)>0:
        with open(args.entity_filename) as f:
            entities = [line.rstrip('\n') for line in f]
    else:
        entities = args.entities
        
    text_id_name = args.text_id_name

    parse_sentences_from_file(input_file,entities,text_column_name, text_id_name, output_file)
    
    bertscores = get_anthroscore(output_file)

    df = pd.read_csv(output_file)

    human_scores = np.sum(bertscores[1:,:15],axis=1)
    nonhuman_scores = np.sum(bertscores[1:,15:],axis=1)
    df['anthroscore'] = np.log(human_scores) - np.log(nonhuman_scores)

    df.to_csv(output_file)

    print('Average AnthroScore in %s: %.3f'%(input_file,np.mean(df['anthroscore'])))
    print('AnthroScores for each sentence saved in %s'%(output_file))

if __name__ == '__main__':
    main()

