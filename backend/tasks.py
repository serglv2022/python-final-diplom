import yaml
import requests
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import URLValidator
from django.db import IntegrityError

from backend.models import Shop, Category, ProductInfo, Product, Parameter, ProductParameter
from order.celery import celery_app
from order.settings import EMAIL_HOST_USER


@celery_app.task()
def send_email(message: str, email: str, *args, **kwargs):
    title = 'Title'
    recipient_list = [email]
    from_email = EMAIL_HOST_USER
    try:
        message = EmailMultiAlternatives(subject=title,
                                         body=message,
                                         from_email=from_email,
                                         to=recipient_list)
        message.send()
        return f'Title: {message.subject}, Message:{message.body}'
    except Exception as error:
        raise error


def open_file(shop):
    with open(shop.get_file(), 'r') as file:
        data = yaml.safe_load(file)
    return data


@celery_app.task()
def get_import(url, user_id):
    if url:
        validate_url = URLValidator()
        try:
            validate_url(url)
        except ValidationError as error:
            return {'Status': False, 'Error': str(error)}
        else:
            stream = requests.get(url).content

        data = yaml.load(stream, Loader=yaml.Loader)
        try:
            shop, _ = Shop.objects.get_or_create(name=data['shop'],
                                                 user_id=user_id
                                                 )
        except IntegrityError as error:
            return {'Status': False, 'Error': str(error)}

        for category in data['categories']:
            object, _ = Category.objects.get_or_create(id=category['id'],
                                                       name=category['name']
                                                       )
            object.shops.add(shop.id)
            object.save()

        ProductInfo.objects.filter(shop_id=shop.id).delete()
        for item in data['goods']:
            product, _ = Product.objects.get_or_create(name=item['name'],
                                                       category_id=item['category']
                                                       )
            product_info = ProductInfo.objects.create(product_id=product.id,
                                                      external_id=item['id'],
                                                      model=item['model'],
                                                      price=item['price'],
                                                      price_rrc=item['price_rrc'],
                                                      quantity=item['quantity'],
                                                      shop_id=shop.id
                                                      )
            for name, value in item['parameters'].items():
                parameter_object, _ = Parameter.objects.get_or_create(name=name)
                ProductParameter.objects.create(product_info_id=product_info.id,
                                                parameter_id=parameter_object.id,
                                                value=value
                                                )
        return {'Status': True}
    return {'Status': False, 'Errors': 'There is no url'}
