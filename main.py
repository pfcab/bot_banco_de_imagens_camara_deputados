import os
import re
import json
from datetime import date, timedelta

from bs4 import BeautifulSoup
import requests
import pandas as pd

import commons_upload


def main():
    yesterday = date.today() - timedelta(days=1)
    query_formatted_yesterday = yesterday.strftime("%d/%m/%Y")
    file_name_yesterday = yesterday.strftime("%Y-%m-%d")
    print(file_name_yesterday)

    html_string = get_html_from_image_pages(query_formatted_yesterday)
    
    # parse and find images
    soup = BeautifulSoup(html_string, 'html.parser')
    images = soup.find_all('img')

    images_data = []

    # Create a directory with yesterday's date inside the "images" directory
    directory_name = f"./images/{file_name_yesterday}"
    os.makedirs(directory_name, exist_ok=True)

    for i, image in enumerate(images, 1):
        print(f"{i} of {len(images)}", end="\r")
        parent_div = image.find_parent('div')
        author_data = parent_div.get('data-autor')
        
        if author_data: # skip if no author given
            continue

        alt_text = image.get('alt')
        alt_text = alt_text.replace('&quot;', '"')  # Replace &quot; with "
        
        people_in_image = alt_text.split(".", 1)[-1]
        image_name = get_file_name(file_name_yesterday, alt_text, people_in_image)        
        image_url = image['src']
        extension = image_url.split('.')[-1]
        image_url = image_url.replace(f"PEQ.{extension}", f".{extension}") # get highest quality image
        image_name += f".{extension}"
        
        # Download the image
        response = requests.get(image_url)
        image_file_path = os.path.join(directory_name, image_name)
        save_image(image_file_path, response.content)
        
        congressmen_in_image = find_congressmen_in_alt_text(alt_text)
        image_data = {
            "file_name": image_name,
            "file_path": image_file_path,
            "author": author_data,
            "date": file_name_yesterday,
            "source": image_url,
            "alt_text": alt_text,
            "congressmen": congressmen_in_image,
        }
        images_data.append(image_data)
    
    csv_path = os.path.join(directory_name, "openrefine_input.csv")
    make_openrefine_csv(image_data, csv_path)
    print()


def get_html_from_image_pages(date=None):
    html_string = ""
    i = 1

    while True:

        image_bank_url = f"https://www.camara.leg.br/banco-imagens//maisfotos?pagina={i}"
        if date:
            image_bank_url = f"https://www.camara.leg.br/banco-imagens//maisfotos?pagina={i}&?buscar=&dataInicio={date}&dataFim={date}"
        
        # post html request
        response = requests.post(image_bank_url)
        if response.text:
            if 'img' in response.text:
                html_string += response.text

        if 'id="botao-mais-fotos"' not in response.text: # no pages left
            return html_string


def get_file_name(date: str, alt_text: str, people_in_image: str):
    if people_in_image:
        people_in_image_list = [i for i in people_in_image.split(".") if i]
        people_in_image_list = ",".join([person.split(",")[-1] for person in people_in_image_list]) # get only the name
        return f"{people_in_image_list}, Câmara dos Deputados do Brasil, {date}"
    
    alt_text = alt_text.replace('.', '').replace('"', '')
    return f"{alt_text}, Câmara dos Deputados do Brasil, {date}"


def save_image(image_file_path, response_content):
    base_name, extension = os.path.splitext(image_file_path)
    i = 0
    new_image_file_path = image_file_path
    
    while os.path.exists(new_image_file_path):
        i += 1
        new_image_file_path = f"{base_name}_{i}{extension}"
    
    # TODO: truncate image name if its too long (over 255 characters)
#    new_image_file_path = new_image_file_path.strip()
#    if len(new_image_file_path) > 255:
#        new_image_file_path = new_image_file_path[:200]+f"{i}{extension}"
 
    with open(new_image_file_path, 'wb') as image_file:
        image_file.write(response_content)


def find_congressmen_in_alt_text(alt_text):
    '''
    Find the name, party and state for each congressman on alt text.
    This information is used later to place categories on the image.
    '''
    congressmen_names = re.findall(r'Dep\.\s*([^)]+\))', alt_text)
    if not congressmen_names:
        return None
    
    congressmen_data = {}
    for congressman_name in congressmen_names:
        name, party_state = congressman_name.split("(")
        party, state = party_state.split("-")
        congressmen_data[name.strip()] = {"party": party.strip(),
                                          "state": state.strip(") ")}
    return congressmen_data


def make_openrefine_csv(image_data, csv_file_path):
    '''
    Create the csv to upload images through OpenRefine
    '''
    for image in image_data:
        image["wikitext"] = make_wikitext_column(image)
    
    # Create a DataFrame from the image_data list
    df = pd.DataFrame.from_dict(image_data)
    if "congressmen" in df.columns:
        df = df.drop("congressmen", axis=1)
    
    # Write the DataFrame to a CSV file
    df.to_csv(csv_file_path, index=False)


def make_wikitext_column(image_data):
    '''
    Create the wikitext for the image, including:
        author
        source
        date
        description (alt text)
        license
        relevant categories
    '''

    description = f'''=={"{{"}int:filedesc{"}}"}==
{"{{"}Information
|description={"{{"}pt-br|1={image_data["alt_text"]}{"}}"}
|date={image_data["date"]}
|source={image_data["source"]}
|author={image_data["author"]}
|permission=
|other versions=
{"}}"}

=={"{{"}int:license-header{"}}"}==

{"{{"}Banco de imagens da Câmara dos Deputados{"}}"}
'''
        
    if image_data["deputados"]:
        for name, dados in image_data["deputados"].items():
            description += f'[[Category:{name}]]\n'
            description += f'[[Category:{get_state_category(dados["uf"])}]]\n'
            description += f'[[Category:{get_party_category(dados["partido"])}]]\n'
    return description


def get_state_category(state):
    """
    Get WikiMedia Commons category for given state
    """
    with open("category_per_state.json", "r") as file:
        categories = json.load(file)
        return categories.get(state, "")
    

def get_party_category(party):
    """
    Get WikiMedia Commons category for given party
    """
    with open("category_per_party.json", "r") as file:
        categories = json.load(file)
        return categories.get(party.upper(), "")


if __name__ == "__main__":
    main()