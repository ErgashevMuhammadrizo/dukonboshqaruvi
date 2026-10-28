from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.core.models import User,Store,Product,InventoryMovement
from apps.core.services import create_sale,money
class SalesTests(TestCase):
 def setUp(self):
  self.u=User.objects.create_user(username='owner',password='secure-password-123')
  self.store=Store.objects.create(owner=self.u,name='Sinov do‘kon')
  self.p=Product.objects.create(store=self.store,name='Olma',sku='A',sale_price=Decimal('12000'),stock=Decimal('10'))
 def test_replay_no_double_stock(self):
  payload={'operation_id':'61ad9719-cebd-4551-ae32-923fd3db6b13','items':[{'product_id':self.p.id,'quantity':'2'}],'cash':'24000','card':'0'}
  sale,created=create_sale(self.store,payload);again,second=create_sale(self.store,payload)
  self.p.refresh_from_db()
  self.assertTrue(created);self.assertFalse(second);self.assertEqual(sale.pk,again.pk);self.assertEqual(self.p.stock,8)
  self.assertEqual(InventoryMovement.objects.count(),1)
 def test_atomic_failed_payment(self):
  with self.assertRaises(ValidationError):create_sale(self.store,{'operation_id':'61ad9719-cebd-4551-ae32-923fd3db6b14','items':[{'product_id':self.p.id,'quantity':2}],'cash':'3'})
  self.p.refresh_from_db();self.assertEqual(self.p.stock,10)
 def test_sale_can_record_customer_debt(self):
  from apps.core.models import DebtRecord
  payload={
   'operation_id':'c2df2b9c-fc83-4858-b3d4-7d1d0fdf4b6a',
   'items':[{'product_id':self.p.id,'quantity':'2'}],
   'cash':'20000','card':'0','debt':'4000','customer_name':'Ali Valiyev',
  }
  sale,created=create_sale(self.store,payload)
  self.assertTrue(created)
  self.assertEqual(sale.total,Decimal('24000.00'))
  self.assertEqual(DebtRecord.objects.filter(store=self.store,direction='customer').count(),1)
  debt=DebtRecord.objects.get(store=self.store,direction='customer')
  self.assertEqual(debt.party_name,'Ali Valiyev')
  self.assertEqual(debt.amount,Decimal('4000.00'))
  self.assertEqual(debt.balance,Decimal('4000.00'))
  self.p.refresh_from_db();self.assertEqual(self.p.stock,8)
 def test_rounding(self):self.assertEqual(money('1.005'),Decimal('1.01'))
class TenantTests(TestCase):
 def setUp(self):
  self.owner1=User.objects.create_user(username='shop1',password='Secure-passphrase-123')
  self.owner2=User.objects.create_user(username='shop2',password='Secure-passphrase-456')
  self.store1=Store.objects.create(owner=self.owner1,name='A')
  self.store2=Store.objects.create(owner=self.owner2,name='B')
  self.product=Product.objects.create(store=self.store1,name='Yashirin',sku='A1',sale_price=10,stock=5)
 def test_other_store_cannot_read_product(self):
  from rest_framework.test import APIClient
  c=APIClient();c.force_authenticate(self.owner2)
  self.assertEqual(c.get(f'/api/v1/products/{self.product.pk}/').status_code,404)
 def test_other_store_cannot_sell_product(self):
  from rest_framework.test import APIClient
  c=APIClient();c.force_authenticate(self.owner2)
  result=c.post('/api/v1/sync/push/',{'operations':[{'operation_id':'f4f7a6a1-a1de-4da6-8307-5f5a70b84645','type':'sale','payload':{'items':[{'product_id':self.product.id,'quantity':1}],'cash':'10','card':'0'}}]},format='json')
  self.assertEqual(result.status_code,200)
  self.assertEqual(result.data['results'][0]['status'],'conflict')
  self.product.refresh_from_db();self.assertEqual(self.product.stock,5)

class ProductAndReportTests(TestCase):
 def setUp(self):
  from rest_framework.test import APIClient
  from datetime import timedelta
  from django.utils import timezone
  from apps.core.models import Subscription
  self.owner=User.objects.create_user(username='report-owner',password='secure-password-123')
  self.store=Store.objects.create(owner=self.owner,name='Hisobot do‘koni')
  Subscription.objects.create(store=self.store,trial_start=timezone.now(),trial_end=timezone.now()+timedelta(days=7))
  self.product=Product.objects.create(store=self.store,name='Non',sku='NON-1',barcode='4781234567890',sale_price=Decimal('2500'),stock=Decimal('3'),min_stock=Decimal('3'))
  self.client=APIClient();self.client.force_authenticate(self.owner)

 def test_barcode_search_and_low_stock_report_are_store_scoped(self):
  found=self.client.get('/api/v1/products/',{'q':'4781234567890'})
  self.assertEqual(found.status_code,200)
  self.assertEqual(found.data[0]['id'],self.product.id)
  summary=self.client.get('/api/v1/reports/summary/')
  self.assertEqual(summary.status_code,200)
  self.assertEqual(summary.data['low_stock'][0]['name'],'Non')
  self.assertEqual(summary.data['out_of_stock'],[])

 def test_report_totals_use_sale_snapshots_and_date_filter(self):
  create_sale(self.store,{
   'operation_id':'a7bbf18e-86e9-40af-8c8e-4e3b2f0a13b9',
   'items':[{'product_id':self.product.id,'quantity':'2'}],
   'cash':'5000','card':'0',
  })
  summary=self.client.get('/api/v1/reports/summary/',{'start':'2000-01-01','end':'2000-01-02'})
  self.assertEqual(summary.data['sales_count'],0)
  summary=self.client.get('/api/v1/reports/summary/')
  self.assertEqual(Decimal(str(summary.data['revenue'])),Decimal('5000.00'))
  self.assertEqual(Decimal(str(summary.data['average_check'])),Decimal('5000.00'))
  self.assertEqual(Decimal(str(summary.data['items_sold'])),Decimal('2'))
  self.assertEqual(summary.data['top_products'][0]['name'],'Non')

 def test_delete_unused_product_and_protect_history(self):
  unused=Product.objects.create(store=self.store,name='Yangi',sku='NEW-DELETE',sale_price='10')
  response=self.client.delete(f'/api/v1/products/{unused.pk}/')
  self.assertEqual(response.status_code,204)
  self.assertFalse(Product.objects.filter(pk=unused.pk).exists())
  create_sale(self.store,{'operation_id':'f5e913f6-d901-4601-9589-d9c104745116','items':[{'product_id':self.product.pk,'quantity':'1'}],'cash':'2500','card':'0'})
  response=self.client.delete(f'/api/v1/products/{self.product.pk}/')
  self.assertEqual(response.status_code,409)
  self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

 def test_delete_other_store_product_forbidden(self):
  other=User.objects.create_user(username='delete-other',password='secure-password-123')
  other_store=Store.objects.create(owner=other,name='Boshqa')
  product=Product.objects.create(store=other_store,name='Boshqa',sku='OTHER',sale_price='10')
  self.assertEqual(self.client.delete(f'/api/v1/products/{product.pk}/').status_code,404)
  self.assertTrue(Product.objects.filter(pk=product.pk).exists())

 def test_product_image_is_returned_by_api(self):
  import tempfile
  from io import BytesIO
  from PIL import Image
  from django.test import override_settings
  from django.core.files.uploadedfile import SimpleUploadedFile
  image_bytes=BytesIO()
  Image.new('RGBA',(1,1),(255,255,255,0)).save(image_bytes,format='PNG')
  image=SimpleUploadedFile('non.png',image_bytes.getvalue(),'image/png')
  with tempfile.TemporaryDirectory() as media_dir, override_settings(MEDIA_ROOT=media_dir):
   response=self.client.post('/api/v1/products/',{
    'name':'Non rasmi','sku':'NON-IMG','sale_price':'2500','purchase_price':'1500',
    'barcode':'4789999999999','initial_stock':'10','min_stock':'3','unit':'dona','image':image,
   },format='multipart')
   self.assertEqual(response.status_code,201,response.data)
   self.assertTrue(response.data['image'])
   created=Product.objects.get(sku='NON-IMG')
   self.assertEqual(created.stock,Decimal('10'))
   from django.test import RequestFactory
   from config.urls import serve_media
   image_response=serve_media(RequestFactory().get(created.image.url),created.image.name)
   self.assertEqual(image_response.status_code,200)
   self.assertEqual(image_response['Content-Type'],'image/png')
   with override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'], SECURE_SSL_REDIRECT=False):
    served=self.client.get(created.image.url)
    self.assertEqual(served.status_code,200)
    served.close()

class DebtApiTests(TestCase):
 def setUp(self):
  from rest_framework.test import APIClient
  self.owner=User.objects.create_user(username='debt-owner',password='secure-password-123')
  self.other=User.objects.create_user(username='debt-other',password='secure-password-456')
  self.store=Store.objects.create(owner=self.owner,name='Daftar do‘koni')
  self.other_store=Store.objects.create(owner=self.other,name='Boshqa do‘kon')
  self.client=APIClient();self.client.force_authenticate(self.owner)

 def test_partial_full_payment_and_idempotency(self):
  from apps.core.models import DebtRecord,DebtPayment
  debt=DebtRecord.objects.create(store=self.store,direction='customer',party_name='Ali',amount='100.00')
  url=f'/api/v1/debts/{debt.pk}/payments/'
  payload={'operation_id':'53dcba28-8d32-4d13-96f6-fc3d6750f77f','amount':'40.00','method':'cash','paid_on':'2026-10-22'}
  first=self.client.post(url,payload,format='json');again=self.client.post(url,payload,format='json')
  self.assertEqual(first.status_code,201,first.data);self.assertEqual(again.status_code,200)
  self.assertEqual(DebtPayment.objects.count(),1);self.assertEqual(first.data['id'],again.data['id'])
  self.assertEqual(self.client.get(f'/api/v1/debts/{debt.pk}/').data['balance'],'60.00')
  payload.update(operation_id='229d295d-f96b-4667-aec8-16fb4a34c9b0',amount='60.00')
  self.assertEqual(self.client.post(url,payload,format='json').status_code,201)
  result=self.client.get(f'/api/v1/debts/{debt.pk}/')
  self.assertEqual(result.data['balance'],'0.00');self.assertEqual(result.data['status'],'paid')

 def test_invalid_payment_and_other_store_isolation(self):
  from apps.core.models import DebtRecord,DebtPayment
  debt=DebtRecord.objects.create(store=self.store,direction='store',party_name='Ta’minotchi',amount='10.00')
  url=f'/api/v1/debts/{debt.pk}/payments/'
  payload={'operation_id':'229d295d-f96b-4667-aec8-16fb4a34c9b1','amount':'11.00','method':'cash','paid_on':'2026-10-22'}
  self.assertEqual(self.client.post(url,payload,format='json').status_code,400)
  payload['amount']='-1.00';self.assertEqual(self.client.post(url,payload,format='json').status_code,400)
  self.assertEqual(DebtPayment.objects.count(),0)
  client=self.client.__class__();client.force_authenticate(self.other)
  self.assertEqual(client.get(f'/api/v1/debts/{debt.pk}/').status_code,404)
  self.assertEqual(client.get('/api/v1/debts/').data,[])

 def test_debt_creation_and_unauthenticated_access(self):
  response=self.client.post('/api/v1/debts/',{'direction':'customer','party_name':'Vali','amount':'25.50','created_on':'2026-10-22'},format='json')
  self.assertEqual(response.status_code,201,response.data)
  self.assertEqual(response.data['balance'],'25.50')
  from rest_framework.test import APIClient
  self.assertEqual(APIClient().get('/api/v1/debts/').status_code,401)

 def test_debt_list_filters_and_sort(self):
  import uuid
  from datetime import timedelta
  from django.utils import timezone
  from apps.core.models import DebtRecord,DebtPayment
  today=timezone.localdate()
  old=DebtRecord.objects.create(store=self.store,direction='customer',party_name='Ali',phone='99890',amount='100.00',created_on=today-timedelta(days=4),due_date=today-timedelta(days=1))
  paid=DebtRecord.objects.create(store=self.store,direction='customer',party_name='Vali',amount='50.00',created_on=today)
  DebtPayment.objects.create(debt=paid,operation_id=uuid.uuid4(),amount='20.00',created_by=self.owner)
  DebtPayment.objects.create(debt=paid,operation_id=uuid.uuid4(),amount='30.00',created_by=self.owner)
  overdue=self.client.get('/api/v1/debts/',{'status':'overdue'})
  self.assertEqual([d['id'] for d in overdue.data],[old.pk])
  self.assertEqual(self.client.get('/api/v1/debts/',{'status':'paid'}).data[0]['id'],paid.pk)
  self.assertEqual(self.client.get('/api/v1/debts/',{'due':'today'}).data,[])
  self.assertEqual(self.client.get('/api/v1/debts/',{'q':'99890'}).data[0]['id'],old.pk)

 def test_product_barcode_sale_stock_history_and_discounted_reports(self):
  from django.utils import timezone
  from apps.core.models import Sale, SaleItem, Subscription
  Subscription.objects.create(store=self.store,trial_start=timezone.now(),
                              trial_end=timezone.now()+timezone.timedelta(days=30))
  created=self.client.post('/api/v1/products/',{
   'name':'Sut','sku':'SUT-1','barcode':'4780000000001',
   'purchase_price':'1500','sale_price':'2500','initial_stock':'3',
   'min_stock':'1','unit':'dona',
  },format='json')
  self.assertEqual(created.status_code,201,created.data)
  product_id=created.data['id']
  second_created=self.client.post('/api/v1/products/',{
   'name':'Choy','sku':'CHOY-1','barcode':'4780000000002',
   'purchase_price':'500','sale_price':'1000','initial_stock':'2',
   'min_stock':'1','unit':'dona',
  },format='json')
  self.assertEqual(second_created.status_code,201,second_created.data)
  second_product_id=second_created.data['id']
  found=self.client.get('/api/v1/products/',{'q':'4780000000001'})
  self.assertEqual(found.status_code,200)
  self.assertEqual(found.data[0]['id'],product_id)

  operation_id='7fa2cd9b-8f32-4a5e-a42a-7ce6bf6f5e13'
  checkout={
   'operation_id':operation_id,
   'items':[{'product_id':product_id,'quantity':'2','unit_price':'1'},
            {'product_id':second_product_id,'quantity':'1','unit_price':'1'}],
   'discount':'600','cash':'5400','card':'0',
  }
  result=self.client.post('/api/v1/sales/',checkout,format='json')
  self.assertEqual(result.status_code,201,result.data)
  self.assertEqual(Decimal(str(result.data['subtotal'])),Decimal('6000.00'))
  self.assertEqual(Decimal(str(result.data['total'])),Decimal('5400.00'))
  # Client values are not trusted for authoritative price or payment.
  replay=self.client.post('/api/v1/sales/',checkout,format='json')
  self.assertEqual(replay.status_code,200,replay.data)
  self.assertEqual(replay.data['id'],result.data['id'])

  product=Product.objects.get(pk=product_id)
  self.assertEqual(product.stock,Decimal('1'))
  second_product=Product.objects.get(pk=second_product_id)
  self.assertEqual(second_product.stock,Decimal('1'))
  sale=Sale.objects.get(operation_id=operation_id)
  item=SaleItem.objects.get(sale=sale,product=product)
  self.assertEqual(item.unit_price,Decimal('2500.00'))
  self.assertEqual(item.quantity,Decimal('2.000'))
  self.assertEqual(InventoryMovement.objects.filter(kind='sale').count(),2)

  history=self.client.get('/api/v1/sales/')
  self.assertEqual(history.status_code,200)
  self.assertEqual(history.data[0]['id'],result.data['id'])
  report=self.client.get('/api/v1/reports/summary/')
  self.assertEqual(report.status_code,200)
  self.assertEqual(Decimal(str(report.data['revenue'])),Decimal('5400.00'))
  self.assertEqual(Decimal(str(report.data['daily'][0]['revenue'])),Decimal('5400.00'))
  self.assertEqual(Decimal(str(report.data['items_sold'])),Decimal('3'))
  self.assertEqual(Decimal(str(report.data['top_products'][0]['revenue'])),Decimal('4500.00'))
  self.assertEqual(Decimal(str(report.data['top_products'][1]['revenue'])),Decimal('900.00'))
