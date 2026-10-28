from decimal import Decimal
from datetime import date
from itertools import groupby
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Sum,Count,F, Q
from django.utils import timezone
from django.core.exceptions import ValidationError as DjangoError
from django.shortcuts import render
from rest_framework import serializers,status,viewsets,mixins
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny,IsAdminUser,BasePermission
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken
from .auth_refresh import SafeTokenRefreshView as TokenRefreshView
from django.contrib.auth import authenticate
from .models import *
from .services import create_sale,redeem_credential,issue_credential,money
import uuid

def err(exc):
    return Response({'error':{'code':'invalid_request','message':str(exc)}},status=400)
class SuperuserOnly(BasePermission):
    def has_permission(self,request,view):return bool(request.user and request.user.is_authenticated and request.user.is_superuser)
class AuthLogin(APIView):
    permission_classes=[AllowAny]
    throttle_scope='auth'
    def post(self,request):
        user=authenticate(username=request.data.get('username',''),password=request.data.get('password',''))
        if user is None: return Response({'error':{'code':'invalid_credentials','message':'Login yoki parol xato'}},status=401)
        t=RefreshToken.for_user(user)
        return Response({'access':str(t.access_token),'refresh':str(t)})
class CredentialRedeem(APIView):
    permission_classes=[AllowAny]
    throttle_scope='auth'
    purpose='activation'
    def post(self,request):
        try:
            user=redeem_credential(request.data['code'],self.purpose,request.data['password'])
            return Response({'message':'Parol o‘rnatildi','username':user.username})
        except (KeyError,DjangoError,ValueError) as e: return err(e)
class ResetRedeem(CredentialRedeem): purpose='reset'
class Logout(APIView):
    def post(self,request):
        try: RefreshToken(request.data['refresh']).blacklist(); return Response(status=204)
        except Exception: return err('Token yaroqsiz')
class Me(APIView):
    def get(self,request):
        store=getattr(request.user,'store',None)
        sub=getattr(store,'subscription',None) if store else None
        now=timezone.now()
        expiry=max((x for x in [getattr(sub,'trial_end',None),getattr(sub,'paid_until',None)] if x),default=None)
        history=SubscriptionHistory.objects.filter(store=store).select_related('plan').order_by('-created_at').first() if store else None
        plan_name=history.plan_name if history else None
        return Response({
            'id': request.user.id,
            'username': request.user.username,
            'first_name': request.user.first_name,
            'last_name': request.user.last_name,
            'email': request.user.email,
            'date_joined': request.user.date_joined,
            'is_active': request.user.is_active,
            'store': getattr(store,'name',None),
            'store_phone': getattr(store,'phone',None),
            'subscription': {'active': bool(expiry and expiry>now), 'expires_at': expiry,
                             'status': 'active' if expiry and expiry>now else 'expired',
                             'plan': plan_name},
            'superadmin': request.user.is_superuser,
            'is_superadmin': request.user.is_superuser,
            'is_admin': request.user.is_superuser,
        })

    def patch(self,request):
        allowed=('first_name','last_name','email')
        for field in allowed:
            if field in request.data:
                setattr(request.user,field,str(request.data[field]).strip())
        changed=list(field for field in allowed if field in request.data)
        if not changed: return self.get(request)
        try: request.user.full_clean(exclude=['password'])
        except DjangoError as exc: return err(exc)
        request.user.save(update_fields=changed)
        return self.get(request)

class ChangeUsername(APIView):
    throttle_scope='auth'
    def post(self,request):
        from django.contrib.auth.validators import UnicodeUsernameValidator
        from django.core.exceptions import ValidationError
        from django.db.models.functions import Lower
        new=str(request.data.get('username','')).strip()
        if not new: return err('Yangi username kiriting')
        try: UnicodeUsernameValidator()(new)
        except ValidationError: return err('Username formati noto‘g‘ri')
        if User.objects.annotate(lower=Lower('username')).filter(lower=new.lower()).exclude(pk=request.user.pk).exists():
            return err('Bu username band')
        old=request.user.username
        request.user.username=new
        try: request.user.save(update_fields=['username'])
        except DjangoError as exc: return err(exc)
        except Exception: return err('Username saqlanmadi')
        AuditLog.objects.create(actor=request.user,action='username_changed',target=f'user:{request.user.pk}',metadata={'old':old,'new':new})
        return Response({'username':new})

class TenantMixin:
    def get_store(self):
        if not hasattr(self.request.user,'store'): raise serializers.ValidationError('Do‘kon biriktirilmagan')
        return self.request.user.store
    def get_queryset(self): return super().get_queryset().filter(store=self.get_store())
    def perform_create(self,serializer): serializer.save(store=self.get_store())

class DebtPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model=DebtPayment
        fields=['id','operation_id','amount','method','paid_on','note','created_at']
        read_only_fields=['id','created_at']

class DebtSerializer(serializers.ModelSerializer):
    paid=serializers.DecimalField(max_digits=18,decimal_places=2,read_only=True)
    balance=serializers.DecimalField(max_digits=18,decimal_places=2,read_only=True)
    status=serializers.SerializerMethodField()
    class Meta:
        model=DebtRecord
        fields=['id','direction','party_name','phone','amount','paid','balance','reason','note','created_on','due_date','created_at','status']
        read_only_fields=['id','created_at']
    def get_status(self,obj):
        if obj.balance <= 0: return 'paid'
        if obj.due_date and obj.due_date < timezone.localdate(): return 'overdue'
        if obj.paid > 0: return 'partial'
        return 'open'
    def validate(self,attrs):
        if attrs.get('direction') not in dict(DebtRecord.DIRECTIONS): raise serializers.ValidationError({'direction':'Qarz turi noto‘g‘ri'})
        return attrs

class Debts(APIView):
    def get(self,request):
        store=getattr(request.user,'store',None)
        if store is None: return err('Do‘kon biriktirilmagan')
        qs=DebtRecord.objects.filter(store=store).prefetch_related('payments').order_by('-created_at')
        direction=request.query_params.get('direction')
        search=request.query_params.get('q','').strip()
        if direction in dict(DebtRecord.DIRECTIONS): qs=qs.filter(direction=direction)
        if search: qs=qs.filter(Q(party_name__icontains=search)|Q(phone__icontains=search))
        for param,lookup in [('start','created_on__gte'),('end','created_on__lte')]:
            raw=request.query_params.get(param)
            if raw:
                try: date.fromisoformat(raw)
                except ValueError: return err(f'{param} sanasi YYYY-MM-DD formatida bo‘lishi kerak')
                qs=qs.filter(**{lookup:raw})
        if request.query_params.get('start') and request.query_params.get('end') and request.query_params['start'] > request.query_params['end']:
            return err('Boshlanish sanasi tugash sanasidan keyin bo‘lishi mumkin emas')
        status_filter=request.query_params.get('status')
        if status_filter:
            qs=qs.annotate(paid_total=Sum('payments__amount'))
            if status_filter == 'paid': qs=qs.filter(paid_total__gte=F('amount'))
            elif status_filter == 'partial': qs=qs.filter(paid_total__gt=0,paid_total__lt=F('amount'))
            elif status_filter == 'overdue': qs=qs.filter(due_date__lt=timezone.localdate()).filter(Q(paid_total__lt=F('amount'))|Q(paid_total__isnull=True))
            elif status_filter == 'open': qs=qs.filter(Q(paid_total__lt=F('amount'))|Q(paid_total__isnull=True))
        due_filter=request.query_params.get('due')
        if due_filter == 'today':
            qs=qs.annotate(paid_total=Sum('payments__amount')).filter(due_date=timezone.localdate()).filter(Q(paid_total__lt=F('amount'))|Q(paid_total__isnull=True))
        elif due_filter == 'overdue':
            qs=qs.annotate(paid_total=Sum('payments__amount')).filter(due_date__lt=timezone.localdate()).filter(Q(paid_total__lt=F('amount'))|Q(paid_total__isnull=True))
        sort=request.query_params.get('sort')
        if sort == 'largest': qs=qs.order_by('-amount','-created_at')
        elif sort == 'oldest': qs=qs.order_by('created_at')
        elif sort == 'overdue': qs=qs.order_by('due_date','created_at')
        return Response(DebtSerializer(qs,many=True).data)
    def post(self,request):
        store=getattr(request.user,'store',None)
        if store is None: return err('Do‘kon biriktirilmagan')
        serializer=DebtSerializer(data=request.data)
        if not serializer.is_valid(): return Response({'error':{'code':'invalid_request','message':serializer.errors}},status=400)
        debt=serializer.save(store=store)
        AuditLog.objects.create(actor=request.user,action='debt_created',target=str(debt.pk),metadata={'direction':debt.direction,'amount':str(debt.amount)})
        return Response(DebtSerializer(debt).data,status=201)

class DebtDetail(APIView):
    def get_debt(self,request,pk):
        return DebtRecord.objects.prefetch_related('payments').filter(store=getattr(request.user,'store',None),pk=pk).first()
    def get(self,request,pk):
        debt=self.get_debt(request,pk)
        if debt is None: return Response(status=404)
        data=DebtSerializer(debt).data
        data['payments']=DebtPaymentSerializer(debt.payments.order_by('-created_at'),many=True).data
        return Response(data)
    def patch(self,request,pk):
        debt=self.get_debt(request,pk)
        if debt is None: return Response(status=404)
        if set(request.data.keys()) - {'note','due_date'}:
            return err('Faqat izoh va to‘lov muddatini o‘zgartirish mumkin')
        serializer=DebtSerializer(debt,data=request.data,partial=True)
        if not serializer.is_valid(): return Response({'error':{'code':'invalid_request','message':serializer.errors}},status=400)
        serializer.save()
        AuditLog.objects.create(actor=request.user,action='debt_updated',target=str(debt.pk))
        return Response(serializer.data)

class DebtPayments(APIView):
    def post(self,request,pk):
        store=getattr(request.user,'store',None)
        operation=request.data.get('operation_id')
        try: operation=uuid.UUID(str(operation))
        except (ValueError,TypeError): return err('operation_id UUID bo‘lishi kerak')
        try:
            with transaction.atomic():
                debt=DebtRecord.objects.select_for_update().get(store=store,pk=pk)
                existing=DebtPayment.objects.filter(debt=debt,operation_id=operation).first()
                if existing: return Response(DebtPaymentSerializer(existing).data)
                serializer=DebtPaymentSerializer(data=request.data)
                if not serializer.is_valid(): return Response({'error':{'code':'invalid_request','message':serializer.errors}},status=400)
                amount=serializer.validated_data['amount']
                if amount > debt.balance: return err('To‘lov qoldiqdan katta bo‘lishi mumkin emas')
                payment=serializer.save(debt=debt,created_by=request.user)
                AuditLog.objects.create(actor=request.user,action='debt_payment_created',target=str(debt.pk),metadata={'payment_id':payment.pk,'amount':str(amount)})
                return Response(DebtPaymentSerializer(payment).data,status=201)
        except DebtRecord.DoesNotExist: return Response(status=404)
class CategorySerializer(serializers.ModelSerializer):
    class Meta: model=Category; fields=['id','name']; read_only_fields=['id']
class ProductSerializer(serializers.ModelSerializer):
    # Boshlang‘ich qoldiq faqat yaratishda qabul qilinadi; keyingi
    # o‘zgarishlar alohida ombor harakati orqali qayd etiladi.
    initial_stock = serializers.DecimalField(max_digits=16, decimal_places=3,
                                             write_only=True, required=False, min_value=0)
    class Meta:
        model=Product
        fields=['id','name','sku','barcode','category','purchase_price','sale_price',
                'stock','initial_stock','unit','min_stock','image','active','updated_at']
        read_only_fields=['id','stock','updated_at']
    def validate_image(self,value):
        if value and value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError('Rasm hajmi 5 MB dan oshmasligi kerak')
        return value
    def validate(self,attrs):
        category=attrs.get('category')
        if category and category.store_id != self.context['request'].user.store.id:
            raise serializers.ValidationError('Toifa boshqa do‘konga tegishli')
        unit=attrs.get('unit',getattr(self.instance,'unit','dona'))
        fractional={'kg','gramm','litr','ml','metr','m²','m³'}
        initial=attrs.get('initial_stock',Decimal('0'))
        minimum=attrs.get('min_stock',getattr(self.instance,'min_stock',Decimal('0')))
        if unit not in {'dona','kg','gramm','litr','ml','metr','m²','m³','quti','paket','pachka','butilka'}:
            raise serializers.ValidationError({'unit':'O‘lchov birligi noto‘g‘ri'})
        if unit not in fractional and (initial%1 or minimum%1):
            raise serializers.ValidationError('Bu birlikda faqat butun miqdor kiritiladi')
        if self.instance and 'initial_stock' in attrs:
            raise serializers.ValidationError({'initial_stock':'Qoldiqni ombor harakati orqali o‘zgartiring'})
        return attrs
    @transaction.atomic
    def create(self,validated_data):
        store=validated_data['store']
        Store.objects.select_for_update().get(pk=store.pk)
        current=SubscriptionHistory.objects.filter(store=store,status='active',ends_at__gt=timezone.now()).select_related('plan').order_by('-ends_at').first()
        plan=current.plan if current else SubscriptionPlan.objects.filter(active=True,code='standard').first()
        if plan and Product.objects.filter(store=store,active=True).count() >= plan.product_limit:
            raise serializers.ValidationError(f'Tarifingizda {plan.product_limit} ta faol mahsulot limiti mavjud. Davom etish uchun tarifni yangilang.')
        initial=validated_data.pop('initial_stock',Decimal('0'))
        product=super().create(validated_data)
        if initial:
            product.stock=initial
            product.save(update_fields=['stock','updated_at'])
            InventoryMovement.objects.create(store=product.store,product=product,
                kind='adjustment',delta=initial,before=Decimal('0'),after=initial,
                reference='Boshlang‘ich qoldiq')
        return product
class CategoryView(TenantMixin,viewsets.ModelViewSet):
    queryset=Category.objects.all(); serializer_class=CategorySerializer
    http_method_names=['get','post','patch','head','options']
class ProductView(TenantMixin,viewsets.ModelViewSet):
    queryset=Product.objects.all(); serializer_class=ProductSerializer
    parser_classes=[JSONParser,MultiPartParser,FormParser]
    http_method_names=['get','post','patch','delete','head','options']
    def destroy(self,request,*args,**kwargs):
        product=self.get_object()
        try:
            with transaction.atomic():
                product.delete()
        except ProtectedError:
            return Response({'error':{'code':'product_has_history','message':'Mahsulot savdo yoki ombor tarixida mavjud. Uni arxivlang.'}},status=409)
        return Response(status=204)
    def get_queryset(self):
        qs=super().get_queryset()
        q=self.request.query_params.get('q')
        if q: qs=qs.filter(Q(name__icontains=q)|Q(sku__icontains=q)|Q(barcode__icontains=q))
        return qs.order_by('id')
    def create(self,request,*args,**kwargs):
        store=getattr(request.user,'store',None)
        if store is None: return err('Do‘kon biriktirilmagan')
        if not entitlement_active(store):
            return Response({'error':{'code':'subscription_expired','message':'Obuna muddati tugagan. Mavjud ma’lumotlaringiz saqlanadi; mahsulot qo‘shish uchun tarifni yangilang.'}},status=403)
        return super().create(request,*args,**kwargs)
    def perform_update(self,serializer):
        store=self.get_store()
        with transaction.atomic():
            Store.objects.select_for_update().get(pk=store.pk)
            product=serializer.instance
            activate=serializer.validated_data.get('active',product.active) and not product.active
            if activate:
                history=SubscriptionHistory.objects.filter(store=store,status='active',ends_at__gt=timezone.now()).select_related('plan').order_by('-ends_at').first()
                plan=history.plan if history else SubscriptionPlan.objects.filter(active=True,code='standard').first()
                if plan and Product.objects.filter(store=store,active=True).exclude(pk=product.pk).count() >= plan.product_limit:
                    raise serializers.ValidationError(f'Tarifingizda {plan.product_limit} ta faol mahsulot limiti mavjud. Tarifni yangilang.')
            serializer.save()
    @action(detail=True,methods=['post'])
    def archive(self,request,pk=None):
        p=self.get_object();p.active=False;p.save(update_fields=['active']);return Response({'active':False})
class StoreView(APIView):
    def get(self,request):
        s=request.user.store; return Response({'name':s.name,'phone':s.phone})
    def patch(self,request):
        s=request.user.store
        for field in ('name','phone'):
            if field in request.data: setattr(s,field,str(request.data[field])[:200])
        s.full_clean();s.save();return self.get(request)
class Adjustment(APIView):
    def post(self,request):
        if not entitlement_active(request.user.store): return Response({"error":{"code":"subscription_expired","message":"Obuna muddati tugagan"}},status=403)
        try:
            with transaction.atomic():
                p=Product.objects.select_for_update().get(pk=request.data['product_id'],store=request.user.store)
                delta=Decimal(str(request.data['delta']))
                if delta==0 or delta.as_tuple().exponent < -3 or p.stock+delta<0: return err('Miqdor xato')
                before=p.stock;p.stock+=delta;p.save(update_fields=['stock','updated_at'])
                m=InventoryMovement.objects.create(store=p.store,product=p,kind='adjustment',delta=delta,before=before,after=p.stock,reference=str(request.data.get('reason',''))[:150])
                return Response({'id':m.id,'stock':p.stock},status=201)
        except (KeyError,ValueError,Product.DoesNotExist): return err('Mahsulot yoki miqdor xato')
class Inventory(APIView):
    def get(self,request):return Response(list(Product.objects.filter(store=request.user.store).values('id','name','sku','stock','min_stock')))
class Movements(APIView):
    def get(self,request):return Response(list(InventoryMovement.objects.filter(store=request.user.store).order_by('-id')[:100].values('id','product_id','kind','delta','before','after','reference','created_at')))
class SaleSerializer(serializers.ModelSerializer):
    items=serializers.SerializerMethodField()
    class Meta: model=Sale; fields=['id','operation_id','subtotal','discount','total','cash','card','created_at','items']
    def get_items(self,obj):return list(obj.items.order_by('id').values('product_id','name','quantity','unit_price','line_total'))
def entitlement_active(store):
    sub=Subscription.objects.filter(store=store).first()
    now=timezone.now()
    return bool(sub and ((sub.trial_end and sub.trial_end>now) or (sub.paid_until and sub.paid_until>now)))

def top_product_totals(sale_items):
    totals={}
    ordered=sale_items.select_related('sale').order_by('sale_id','id').iterator(chunk_size=1000)
    for _,group in groupby(ordered,key=lambda item:item.sale_id):
        lines=list(group)
        sale=lines[0].sale
        remaining=money(sale.discount)
        for index,item in enumerate(lines):
            if index==len(lines)-1:
                discount_share=remaining
            elif sale.subtotal:
                discount_share=money(sale.discount*item.line_total/sale.subtotal)
            else:
                discount_share=Decimal('0')
            discount_share=min(max(discount_share,Decimal('0')),remaining,item.line_total)
            remaining=money(remaining-discount_share)
            net_line_total=money(item.line_total-discount_share)
            row=totals.setdefault(item.product_id,{
                'product_id':item.product_id,'name':item.name,
                'quantity':Decimal('0'),'revenue':Decimal('0'),
            })
            row['quantity']+=item.quantity
            row['revenue']+=net_line_total
    return sorted(totals.values(),key=lambda row:(-row['quantity'],row['name'].casefold()))[:10]

class SaleView(TenantMixin,viewsets.GenericViewSet,mixins.ListModelMixin,mixins.RetrieveModelMixin):
    queryset=Sale.objects.all().order_by('-created_at');serializer_class=SaleSerializer
    def get_queryset(self):
        qs=super().get_queryset()
        start=self.request.query_params.get('start');end=self.request.query_params.get('end')
        try:
            if start: date.fromisoformat(start[:10])
            if end: date.fromisoformat(end[:10])
        except ValueError: return qs.none()
        if start: qs=qs.filter(created_at__date__gte=start[:10])
        if end: qs=qs.filter(created_at__date__lte=end[:10])
        return qs
    def create(self,request):
        if not entitlement_active(self.get_store()): return Response({"error":{"code":"subscription_expired","message":"Obuna muddati tugagan"}},status=403)
        try:
            sale,created=create_sale(self.get_store(),request.data)
            return Response(self.get_serializer(sale).data,status=201 if created else 200)
        except (KeyError,ValueError,DjangoError) as e:return err(e)
class SyncPush(APIView):
    def post(self,request):
        results=[];store=request.user.store
        for operation in request.data.get('operations',[]):
            opid=operation.get('operation_id')
            try:
                existing=SyncOperation.objects.filter(store=store,operation_id=opid).first()
                if existing:results.append(existing.response);continue
                if operation.get('type')!='sale': raise ValueError('Amal turi qo‘llab-quvvatlanmaydi')
                with transaction.atomic():
                    payload={**operation['payload'],'operation_id':opid}
                    sale,_=create_sale(store,payload)
                    response={'operation_id':opid,'status':'ack','sale_id':str(sale.id)}
                    SyncOperation.objects.create(store=store,operation_id=opid,kind='sale',response=response)
                    results.append(response)
            except (DjangoError,KeyError,ValueError) as e:
                results.append({'operation_id':opid,'status':'conflict','message':str(e)})
        return Response({'results':results})
class SyncPull(APIView):
    def get(self,request):
        s=request.user.store
        return Response({'products':ProductSerializer(Product.objects.filter(store=s),many=True).data,'categories':CategorySerializer(Category.objects.filter(store=s),many=True).data,'server_time':timezone.now()})
class Reports(APIView):
    def get(self,request):
        qs=Sale.objects.filter(store=request.user.store)
        start=request.query_params.get('start');end=request.query_params.get('end')
        try:
            if start: date.fromisoformat(start[:10])
            if end: date.fromisoformat(end[:10])
        except ValueError: return err('Sana formati YYYY-MM-DD bo‘lishi kerak')
        if start: qs=qs.filter(created_at__date__gte=start[:10])
        if end: qs=qs.filter(created_at__date__lte=end[:10])
        a=qs.aggregate(total=Sum('total'),count=Count('id'),cash=Sum('cash'),card=Sum('card'))
        sale_items=SaleItem.objects.filter(sale__in=qs)
        daily_revenue={row['created_at__date']:row['revenue'] for row in qs.values('created_at__date').annotate(revenue=Sum('total')).order_by('created_at__date')}
        daily_quantity=dict(sale_items.values('sale__created_at__date').annotate(quantity=Sum('quantity')).values_list('sale__created_at__date','quantity'))
        days=[{'sale__created_at__date':day,'revenue':revenue,'quantity':daily_quantity.get(day,Decimal('0'))} for day,revenue in daily_revenue.items()]
        top=top_product_totals(sale_items)
        stock=Product.objects.filter(store=request.user.store,active=True)
        low=list(stock.filter(stock__gt=0,stock__lte=F('min_stock')).values('id','name','stock','min_stock'))
        out=list(stock.filter(stock__lte=0).values('id','name','stock','min_stock'))
        quantity=sale_items.aggregate(total=Sum('quantity'))['total'] or Decimal('0')
        total=a['total'] or Decimal('0')
        return Response({'revenue':total,'sales_count':a['count'],'average_check':(total/a['count'] if a['count'] else Decimal('0')),'cash':a['cash'] or 0,'card':a['card'] or 0,'items_sold':quantity,'top_products':list(top),'daily':list(days),'low_stock':low,'out_of_stock':out})
class Status(APIView):
    def get(self,request):
        store=getattr(request.user,'store',None)
        if store is None: return err('Do‘kon biriktirilmagan')
        sub=Subscription.objects.filter(store=store).first(); now=timezone.now()
        expiry=max([x for x in [getattr(sub,'trial_end',None),getattr(sub,'paid_until',None)] if x],default=None)
        history=SubscriptionHistory.objects.filter(store=store).select_related('plan').order_by('-created_at').first()
        return Response({'active':bool(expiry and expiry>now),'expires_at':expiry,'server_time':now,
                         'status': history.status if history and expiry and expiry>now else ('expired' if not expiry or expiry<=now else 'active'),
                         'plan': history.plan_name if history else None})
class Plans(APIView):
    permission_classes=[AllowAny]
    def get(self,request):
        return Response(list(SubscriptionPlan.objects.filter(active=True).values('id','code','name','description','months','price','annual_price','currency','trial_days','user_limit','product_limit','features','discount_percent')))
class Payments(APIView):
    def get(self,request):
        return Response(list(PaymentRecord.objects.filter(store=request.user.store).values(
            'id','order_id','plan_name','provider','provider_transaction_id','amount','currency','status',
            'reference','billing_period','failure_reason','submitted_at','approved_at')))

class SubscriptionHistoryList(APIView):
    def get(self,request):
        rows=list(SubscriptionHistory.objects.filter(store=request.user.store).order_by('-created_at').values(
            'id','plan_name','starts_at','ends_at','status','billing_period','amount','currency','created_at'))
        now=timezone.now()
        for row in rows:
            if row['status']=='active' and row['ends_at'] and row['ends_at']<=now: row['status']='expired'
        return Response(rows)
class AdminIssue(APIView):
    permission_classes=[SuperuserOnly]
    def post(self,request):
        try:
            u=User.objects.get(pk=request.data['user_id'])
            raw=issue_credential(u,request.data['purpose'],request.user)
            return Response({'one_time_code':raw,'warning':'Kodni xavfsiz kanal orqali bir marta yuboring'})
        except (KeyError,User.DoesNotExist) as e:return err(e)

class ChangePassword(APIView):
    throttle_scope='auth'
    def post(self,request):
        from django.contrib.auth.password_validation import validate_password
        try:
            old_password = request.data.get('old_password','')
            new_password = request.data.get('new_password','')
            confirmation=request.data.get('confirm_password','')
            
            if not request.user.check_password(old_password):
                return Response({'error':{'code':'invalid_password','message':'Eski parol xato'}},status=400)
            if new_password != confirmation:
                return err('Yangi parollar mos kelmadi')
            if new_password == old_password:
                return err('Yangi parol joriy paroldan farq qilishi kerak')
            validate_password(new_password, request.user)
            request.user.set_password(new_password)
            request.user.save(update_fields=['password'])
            
            # Blacklist all existing tokens
            from rest_framework_simplejwt.token_blacklist.models import OutstandingToken,BlacklistedToken
            for token in OutstandingToken.objects.filter(user=request.user):
                BlacklistedToken.objects.get_or_create(token=token)
            
            AuditLog.objects.create(actor=request.user,action='password_changed',target=f'user:{request.user.pk}')
            
            return Response({'message':'Parol muvaffaqiyatli o\'zgartirildi'})
        except (KeyError,DjangoError,ValueError) as e:
            return err(e)

def home(request):return render(request,'index.html',{'plans':SubscriptionPlan.objects.filter(active=True)})
