import urllib.request
import fitz
import re
import numpy as np
import tensorflow_hub as hub
import openai
import gradio as gr
import os
from sklearn.neighbors import NearestNeighbors

question = "What is the purpose of data collection?, What is the data that is collected?, what is the purpose of sharing collected data with third parties?, What third parties may get user data?"

def download_pdf(url, output_path):
    urllib.request.urlretrieve(url, output_path)


def preprocess(text):
    text = text.replace('\n', ' ')
    text = re.sub('\s+', ' ', text)
    return text


def pdf_to_text(path, start_page=1, end_page=None):
    doc = fitz.open(path)
    total_pages = doc.page_count

    if end_page is None:
        end_page = total_pages

    text_list = []

    for i in range(start_page-1, end_page):
        text = doc.load_page(i).get_text("text")
        text = preprocess(text)
        text_list.append(text)

    doc.close()
    return text_list


def text_to_chunks(texts, word_length=150, start_page=1):
    text_toks = [t.split(' ') for t in texts]
    page_nums = []
    chunks = []
    
    for idx, words in enumerate(text_toks):
        for i in range(0, len(words), word_length):
            chunk = words[i:i+word_length]
            if (i+word_length) > len(words) and (len(chunk) < word_length) and (
                len(text_toks) != (idx+1)):
                text_toks[idx+1] = chunk + text_toks[idx+1]
                continue
            chunk = ' '.join(chunk).strip()
            chunk = f'[Page no. {idx+start_page}]' + ' ' + '"' + chunk + '"'
            chunks.append(chunk)
    return chunks

class SemanticSearch:
    
    def __init__(self):
        self.use = hub.load('https://tfhub.dev/google/universal-sentence-encoder/4')
        self.fitted = False
    
    
    def fit(self, data, batch=500, n_neighbors=8):
        self.data = data
        self.embeddings = self.get_text_embedding(data, batch=batch)
        n_neighbors = min(n_neighbors, len(self.embeddings))
        self.nn = NearestNeighbors(n_neighbors=n_neighbors)
        self.nn.fit(self.embeddings)
        self.fitted = True
    
    
    def __call__(self, text, return_data=True):
        inp_emb = self.use([text])
        neighbors = self.nn.kneighbors(inp_emb, return_distance=False)[0]
        
        if return_data:
            return [self.data[i] for i in neighbors]
        else:
            return neighbors
    
    
    def get_text_embedding(self, texts, batch=500):
        embeddings = []
        for i in range(0, len(texts), batch):
            text_batch = texts[i:(i+batch)]
            emb_batch = self.use(text_batch)
            embeddings.append(emb_batch)
        embeddings = np.vstack(embeddings)
        return embeddings



def load_recommender(path, start_page=1):
    global recommender
    texts = pdf_to_text(path, start_page=start_page)
    chunks = text_to_chunks(texts, start_page=start_page)
    recommender.fit(chunks)
    return 'Corpus Loaded.'

def generate_text(openAI_key,prompt, engine="text-davinci-003"):
    openai.api_key = openAI_key
    completions = openai.Completion.create(
        engine=engine,
        prompt=prompt,
        max_tokens=2000,
        n=1,
        stop=None,
        temperature=0.9,
    )
    message = completions.choices[0].text +'\n prompt tokens'+ str(completions.usage.prompt_tokens) +'\n completion tokens'+ str(completions.usage.completion_tokens) +'\n total tokens'+ str(completions.usage.total_tokens)
    return message

def generate_answer(openAI_key):
    topn_chunks = recommender(question)
    prompt = ""
    prompt += 'search results:\n\n'
    for c in topn_chunks:
        prompt += c + '\n\n'
        
    prompt += "Instructions: Compose an exhaustive reply to the query using the search results given. "\
                "Extract the entities mentioned in the text, First extract company names(if not mentioned refer to them as 'unnamed third parties'), then extract all data points collected, finally extract what data is being shared with the third parties and what specific purpose they intend to use it for"\
                "Desired format: Company names: <comma_separated_list_of_company_names>  \n User data collected : <comma_separated_list_such_as_name_age_user_behaviour_on_app_IP_websites-visited, include other user data that is being collected from other sources>   \n Data shared with third parties: <comma_Separated_list_of_user_data_shared_with_third_parties>  \n Purpose of data sharing(write_purpose_for_each_third_party_separately):choose from these options(maintaining functionality for end user, User tracking, data aggregation, analytics, targeted advertising) "\
                "If the text does not relate to the privacy policy of an organization, Ignore the questions asked. "\
                "The answer should be somewhat verbose so as to make sense to the common user. Answer all questions comprehensively and break the answers to each question into separate paragraphs using '\n' "\
                "Answer step-by-step. \n\nQuery: {question}\nAnswer: "\

    prompt += f"Query: {question}\nAnswer:"
    answer = generate_text(openAI_key, prompt,"text-davinci-003")
    return answer


def question_answer(url, file, openAI_key):
    if openAI_key.strip()=='':
        return '[ERROR]: Please enter your Open AI Key. Get your key here: https://platform.openai.com/account/api-keys'
    if url.strip() == '' and file == None:
        return '[ERROR]: Both URL and PDF are empty. Provide at least one.'
    
    if url.strip() != '' and file != None:
        return '[ERROR]: Both URL and PDF are provided. Please provide only one (either URL or PDF).'

    if url.strip() != '':
        glob_url = url
        download_pdf(glob_url, 'corpus.pdf')
        load_recommender('corpus.pdf')

    else:
        old_file_name = file.name
        file_name = file.name
        file_name = file_name[:-12] + file_name[-4:]
        os.rename(old_file_name, file_name)
        load_recommender(file_name)

    return generate_answer(openAI_key)


recommender = SemanticSearch()

title = 'Policy Analyzer V1.3'
description = """ Privacy policy reading and consistency analysis using GPT API, using bhaskatripathi's pdfGPT implementation and manual Session capture, decryption and analysis to compare data received from privacy policy against data inferred from session capture."""

with gr.Blocks() as demo:

    gr.Markdown(f'<center><h1>{title}</h1></center>')
    gr.Markdown(description)

    with gr.Row():
        
        with gr.Group():
            gr.Markdown(f'<p style="text-align:center">Get your Open AI API key <a href="https://platform.openai.com/account/api-keys">here</a></p>')
            openAI_key=gr.Textbox(label='Enter your OpenAI API key here')
            url = gr.Textbox(label='Enter PDF URL here')
            gr.Markdown("<center><h4>OR<h4></center>")
            file = gr.File(label='Upload Privacy policy pdf here', file_types=['.pdf'])
            btn = gr.Button(value='Submit')
            btn.style(full_width=True)

        with gr.Group():
            answer = gr.Textbox(label='The data collected, the data shared with third parties, and the purpose it is shared for according to the privacy policy is as follows:')

        btn.click(question_answer, inputs=[url, file, openAI_key], outputs=[answer])
#openai.api_key = os.getenv('Your_Key_Here') 
demo.launch()